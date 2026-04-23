from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Annotated, Any, Callable, Literal, TypedDict

from fastapi import HTTPException
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .booking import (
    BOOKING_TTL_MINUTES,
    build_booking_email_content,
    clear_pending_booking,
    extract_booking_data,
    load_pending_booking,
    parse_pending_payload,
    save_pending_booking,
)
from .db import pgvector_ready, retrieve_similar_chunks
from .email_orchestrator import EmailSendPayload
from .config import settings
from .agents.therapist_agent import (
    TherapistSearchHandler,
    extract_location,
    extract_radius_km,
    extract_specialty,
    get_remembered_location,
    remember_location,
)
from .llm.langchain_model import get_langchain_chat_model
from .llm.provider import ProviderError, ProviderNotConfiguredError, generate_chat
from .mcp_client import ainvoke_mcp_tool, mcp_therapist_search
from .models import PendingAction, User
from .prompts import (
    BOOKING_EMAIL_MASTER_PROMPT,
    COACH_MASTER_PROMPT,
    SAFETY_GATE_MASTER_PROMPT,
)
from .safety import contains_jailbreak_attempt, is_crisis, is_prescription_request, scope_check
from .schemas import BookingProposal, ChatResponse, Resource, TherapistResult


class TherapistSearch(TypedDict, total=False):
    """Typed output contract written by the therapist node into graph state."""
    status: str  # "ok" | "auth_required" | "premium_required" | "needs_location" | "no_results" | "error" | "unavailable"
    results: list[dict[str, Any]]
    message: str | None


class BookingAgentState(TypedDict, total=False):
    """State for the booking subgraph — shares messages/active_node/response_json with parent."""
    messages: Annotated[list[AnyMessage], add_messages]
    active_node: str
    response_json: dict[str, Any]


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    route: Literal["COACH", "THERAPIST_SEARCH", "BOOKING_EMAIL", "FINAL"]
    active_node: str
    sentiment_analysis: dict[str, Any]
    therapist_search: TherapistSearch
    retrieved_chunks: list[dict[str, Any]]
    response_json: dict[str, Any]


class SentimentAgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    sentiment_analysis: dict[str, Any]
    active_node: str


class CoachAgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    sentiment_analysis: dict[str, Any]
    active_node: str


@dataclass
class GraphRuntimeContext:
    db: Session | None = None
    user: User | None = None
    actor_key: str | None = None
    pending_action: PendingAction | None = None
    pending_expired: bool = False
    request: Any | None = None
    therapist_search_fn: Callable[[str, int | None, str | None, int], list[Any]] | None = None
    send_email_fn: Callable[[str, EmailSendPayload], dict[str, Any]] | None = None


class SafetyResourceDecision(BaseModel):
    title: str
    url: str


class SafetyDecision(BaseModel):
    action: Literal["continue", "stop"]
    risk_level: Literal["normal", "crisis", "jailbreak", "medical", "out_of_scope"]
    coach_message: str
    resources: list[SafetyResourceDecision]


class RouteDecision(BaseModel):
    route: Literal["COACH", "THERAPIST_SEARCH", "BOOKING_EMAIL"]


class SentimentAnalysis(BaseModel):
    primary_sentiment: Literal[
        "calm",
        "anxious",
        "stressed",
        "sad",
        "overwhelmed",
        "angry",
        "uncertain",
        "hopeful",
        "mixed",
    ]
    emotional_intensity: Literal["low", "medium", "high"]
    support_style: Literal[
        "warm_and_grounding",
        "calm_and_reassuring",
        "gentle_and_validating",
        "steady_and_structured",
        "encouraging_and_forward_looking",
    ]
    user_needs: list[str]
    coach_handoff: str


def _history_to_messages(history: list[dict[str, str]] | None, message: str) -> list[AnyMessage]:
    messages: list[AnyMessage] = []
    for item in history or []:
        role = item.get("role")
        content = str(item.get("content") or "")
        if not content:
            continue
        if role == "assistant":
            messages.append(AIMessage(content=content))
        else:
            messages.append(HumanMessage(content=content))
    messages.append(HumanMessage(content=message))
    return messages


def _latest_user_message(state: AgentState) -> str:
    for message in reversed(state["messages"]):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def _latest_ai_message(state: AgentState) -> AIMessage | None:
    for message in reversed(state["messages"]):
        if isinstance(message, AIMessage):
            return message
    return None


def _parse_chat_response(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1])
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            payload = json.loads(text[start : end + 1])
            return ChatResponse(**payload).model_dump()
        except Exception:
            pass
    return ChatResponse(coach_message=text or "How can I support you today?").model_dump()


def _graph_model_response(system_prompt: str, state: AgentState, *, tools: list[BaseTool]) -> AIMessage:
    model = get_langchain_chat_model()
    bound = model.bind_tools(tools)
    response = bound.invoke([SystemMessage(content=system_prompt), *state["messages"]])
    if not isinstance(response, AIMessage):
        return AIMessage(content=str(getattr(response, "content", response)))
    return response


def _structured_chat_response(prompt: str, state: AgentState) -> dict[str, Any]:
    model = get_langchain_chat_model(temperature=0)
    structured = model.with_structured_output(ChatResponse)
    result = structured.invoke([SystemMessage(content=prompt), *state["messages"]])
    if isinstance(result, ChatResponse):
        return result.model_dump()
    if isinstance(result, dict):
        return ChatResponse.model_validate(result).model_dump()
    raise ProviderError("structured chat response parsing failed")


def _structured_decision(prompt: str, message: str, model_cls: type[BaseModel]) -> BaseModel:
    model = get_langchain_chat_model(temperature=0)
    structured = model.with_structured_output(model_cls)
    result = structured.invoke([
        SystemMessage(content=prompt),
        HumanMessage(content=message),
    ])
    if isinstance(result, model_cls):
        return result
    if isinstance(result, dict):
        return model_cls.model_validate(result)
    raise ProviderError("structured decision parsing failed")


def _build_tools(context: GraphRuntimeContext) -> tuple[list[BaseTool], list[BaseTool]]:
    def retrieve_context_tool_impl(query: str) -> list[dict[str, Any]]:
        if not pgvector_ready():
            return []
        try:
            return retrieve_similar_chunks(query, top_k=4)
        except ProviderNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def load_pending_booking_tool_impl() -> dict[str, Any]:
        # main.py loads and *deletes* expired rows before the graph runs, setting
        # context.pending_expired = True.  When this tool re-queries the DB the row
        # is already gone, so load_pending_booking returns (None, False) — which
        # would incorrectly overwrite the expired flag.  Capture it first.
        original_expired = context.pending_expired

        if not context.db or not context.actor_key:
            if original_expired:
                return {
                    "status": "EXPIRED",
                    "pending": False,
                    "expired": True,
                    "action_hint": "The booking has expired. Do NOT call send_pending_booking_email. Tell the user it expired and offer to start over.",
                }
            return {
                "status": "NO_PENDING",
                "pending": False,
                "expired": False,
                "action_hint": "No pending booking exists. Ask the user for therapist email and preferred date/time.",
            }

        pending_action, db_expired = load_pending_booking(context.db, context.actor_key)
        expired = db_expired or original_expired  # preserve flag set during context setup
        context.pending_action = pending_action
        context.pending_expired = expired

        if expired:
            return {
                "status": "EXPIRED",
                "pending": False,
                "expired": True,
                "action_hint": "The booking has expired. Do NOT call send_pending_booking_email. Tell the user it expired and offer to start over.",
            }
        if not pending_action:
            return {
                "status": "NO_PENDING",
                "pending": False,
                "expired": False,
                "action_hint": "No pending booking exists. Ask the user for therapist email and preferred date/time.",
            }
        payload = parse_pending_payload(pending_action)
        return {
            "status": "PENDING_READY",
            "pending": True,
            "expired": False,
            "payload": payload,
            "expires_at": pending_action.expires_at.isoformat(),
            "action_hint": (
                f"A complete booking is ready to send to {payload.get('therapist_email', 'unknown')}. "
                "If the user just said YES/confirm/ok/sure, call send_pending_booking_email immediately. "
                "If the user said NO/cancel, call cancel_pending_booking."
            ),
        }

    def prepare_booking_from_message_tool_impl(message: str) -> dict[str, Any]:
        if not context.db or not context.actor_key:
            return {"ok": False, "error": "Booking is unavailable right now."}
        extracted = extract_booking_data(message)

        # Merge with any existing partial pending so multi-turn works correctly.
        # e.g. turn 1 captures email; turn 2 provides the datetime — combine both.
        existing_payload: dict[str, Any] = {}
        if context.pending_action:
            existing_payload = parse_pending_payload(context.pending_action)

        merged_email = extracted.therapist_email or existing_payload.get("therapist_email")
        merged_name = (
            extracted.sender_name
            or existing_payload.get("sender_name")
            or (context.user.name if context.user and context.user.name else None)
        )

        payload: dict[str, Any] = {
            "therapist_email": merged_email,
            "requested_datetime_iso": extracted.requested_datetime.isoformat() if extracted.requested_datetime else None,
            "subject": None,
            "body": None,
            "reply_to": context.user.email if context.user and context.user.email else None,
            "sender_name": merged_name,
            "clarification": extracted.clarification,
        }
        if merged_email and extracted.requested_datetime:
            payload = build_booking_email_content(
                user=context.user,
                therapist_email=merged_email,
                requested_datetime=extracted.requested_datetime,
                sender_name=merged_name,
            )
        pending = save_pending_booking(context.db, context.actor_key, payload)
        context.pending_action = pending
        return {
            "ok": True,
            "payload": payload,
            "expires_at": pending.expires_at.isoformat(),
            "ttl_minutes": BOOKING_TTL_MINUTES,
        }

    async def send_pending_booking_email_tool_impl() -> dict[str, Any]:
        if not context.db or not context.actor_key:
            return {"ok": False, "error": "Booking is unavailable right now."}
        pending_action, expired = load_pending_booking(context.db, context.actor_key)
        context.pending_action = pending_action
        context.pending_expired = expired
        if expired:
            return {"ok": False, "error": "Pending booking expired."}
        if not pending_action:
            return {"ok": False, "error": "No pending booking to send."}
        payload = parse_pending_payload(pending_action)
        if not payload.get("therapist_email") or not payload.get("subject") or not payload.get("body"):
            return {"ok": False, "error": "Pending booking is incomplete."}
        email_payload = EmailSendPayload(
            to=payload["therapist_email"],
            subject=payload["subject"],
            body=payload["body"],
            reply_to=payload.get("reply_to"),
        )
        # Prefer the injected callable so that test monkeypatches are honoured;
        # fall back to the async MCP tool in production where the callable is absent.
        if context.send_email_fn is not None:
            try:
                result = context.send_email_fn(context.actor_key or "", email_payload)
            except Exception as exc:
                return {"ok": False, "error": f"Email send failed: {exc}"}
        else:
            result = await ainvoke_mcp_tool(
                "send_email_tool",
                {
                    "to": email_payload.to,
                    "subject": email_payload.subject,
                    "body": email_payload.body,
                    "reply_to": email_payload.reply_to,
                },
            )
        clear_pending_booking(context.db, pending_action)
        context.pending_action = None
        return {"ok": True, "message": "Email sent successfully.", "result": result}

    def cancel_pending_booking_tool_impl() -> dict[str, Any]:
        if not context.db or not context.actor_key:
            return {"ok": False, "error": "Booking is unavailable right now."}
        pending_action, _ = load_pending_booking(context.db, context.actor_key)
        if not pending_action:
            return {"ok": False, "error": "No pending booking to cancel."}
        clear_pending_booking(context.db, pending_action)
        context.pending_action = None
        return {"ok": True, "message": "Pending booking cancelled."}

    retrieve_context_tool = StructuredTool.from_function(
        func=retrieve_context_tool_impl,
        name="retrieve_context",
        description="Retrieve relevant mental health coaching context for the latest user message.",
    )
    load_pending_booking_tool = StructuredTool.from_function(
        func=load_pending_booking_tool_impl,
        name="load_pending_booking",
        description="Load the currently pending booking request, if any.",
    )
    prepare_booking_from_message_tool = StructuredTool.from_function(
        func=prepare_booking_from_message_tool_impl,
        name="prepare_booking_from_message",
        description="Parse the user message, build an appointment email proposal, and persist it as pending when enough information is present.",
    )
    send_pending_booking_email_tool = StructuredTool.from_function(
        coroutine=send_pending_booking_email_tool_impl,
        name="send_pending_booking_email",
        description="Send the currently pending booking email through MCP and clear the pending request.",
    )
    cancel_pending_booking_tool = StructuredTool.from_function(
        func=cancel_pending_booking_tool_impl,
        name="cancel_pending_booking",
        description="Cancel and clear the current pending booking request.",
    )

    return [retrieve_context_tool], [load_pending_booking_tool, prepare_booking_from_message_tool, send_pending_booking_email_tool, cancel_pending_booking_tool]


def _legacy_classify_risk(state: AgentState) -> AgentState:
    return {"route": "FINAL", "response_json": ChatResponse(
        coach_message=(
            "I am really sorry you are feeling this way. If you are in immediate danger, "
            "please call your local emergency number right now. In Sweden, call 112 for emergencies. "
            "If you can, reach out to someone you trust and let them know you need support."
        ),
        resources=[
            Resource(title="Emergency services (Sweden)", url="https://www.112.se/"),
            Resource(title="Find local crisis lines", url="https://www.iasp.info/resources/Crisis_Centres/"),
        ],
    ).model_dump()} if is_crisis(_latest_user_message(state)) else {"route": "COACH"}


def _legacy_retrieve_context(state: AgentState) -> AgentState:
    message = _latest_user_message(state)
    if not pgvector_ready():
        return {"retrieved_chunks": []}
    try:
        chunks = retrieve_similar_chunks(message, top_k=4)
    except ProviderNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"retrieved_chunks": chunks}


def _legacy_llm_response(state: AgentState) -> AgentState:
    message = _latest_user_message(state)
    history_messages = [
        {"role": "assistant" if isinstance(item, AIMessage) else "user", "content": str(item.content)}
        for item in state["messages"][:-1]
    ]
    content = generate_chat(
        messages=[*history_messages, {"role": "user", "content": message}],
        system_prompt=COACH_MASTER_PROMPT,
        timeout=180.0,
        keep_alive="10m",
        user_message=message,
    )
    return {"response_json": ChatResponse(coach_message=content).model_dump()}


def _legacy_finalize_node(state: AgentState) -> AgentState:
    if state.get("response_json"):
        return {"response_json": state["response_json"]}
    latest_ai = _latest_ai_message(state)
    if latest_ai is None:
        return {"response_json": ChatResponse(coach_message="How can I support you today?").model_dump()}
    return {"response_json": _parse_chat_response(str(latest_ai.content or ""))}


def _legacy_build_graph(
    retrieve_fn: Callable[[AgentState], AgentState] | None = None,
    llm_fn: Callable[[AgentState], AgentState] | None = None,
):
    graph = StateGraph(AgentState)
    graph.add_node("classify", _legacy_classify_risk)
    graph.add_node("retrieve", retrieve_fn or _legacy_retrieve_context)
    graph.add_node("llm", llm_fn or _legacy_llm_response)
    graph.add_node("finalize", _legacy_finalize_node)
    graph.add_edge(START, "classify")
    graph.add_conditional_edges("classify", lambda state: "finalize" if state.get("response_json") else "retrieve")
    graph.add_edge("retrieve", "llm")
    graph.add_edge("llm", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


def make_safety_node(context: GraphRuntimeContext):
    def safety_node(state: AgentState) -> AgentState:
        message = _latest_user_message(state)
        request = context.request

        if is_prescription_request(message):
            return {
                "route": "FINAL",
                "response_json": ChatResponse(
                    coach_message=(
                        "This is beyond my capability. I can't help with prescriptions, dosing, or medication changes. "
                        "Please contact a licensed clinician or pharmacist. If you think you may be in danger "
                        "(e.g., overdose, severe reaction), call 112 immediately in Sweden."
                    ),
                    resources=[
                        Resource(title="Emergency services (Sweden)", url="https://www.112.se/"),
                        Resource(title="Healthcare advice (Sweden)", url="https://www.1177.se/"),
                    ],
                    risk_level="medical",
                ).model_dump(),
            }

        if is_crisis(message):
            location = None
            radius_km = 25
            specialty = extract_specialty(message)
            therapists: list[TherapistResult] | None = None

            if request is not None:
                location = extract_location(message) or get_remembered_location(
                    user=context.user,
                    request=request,
                    session_cookie_name=settings.session_cookie_name,
                )
                radius_km = extract_radius_km(message) or 25

            if location:
                therapist_agent = TherapistSearchHandler(
                    search_fn=context.therapist_search_fn or mcp_therapist_search,
                    dev_mode=True,
                    session_cookie_name=settings.session_cookie_name,
                )
                results, _ = therapist_agent.search_with_retries(
                    location_text=location,
                    radius_km=radius_km,
                    specialty=specialty,
                )
                therapists = [TherapistResult.model_validate(item) for item in results]
                if request is not None:
                    remember_location(
                        user=context.user,
                        request=request,
                        location=location,
                        session_cookie_name=settings.session_cookie_name,
                    )

            coach_message = (
                "I am really glad you reached out. Please seek immediate support right now. "
                "If you might act on these thoughts or are in immediate danger, call 112 immediately. "
                "You can also contact Mind Självmordslinjen at 90101 (chat/phone) for urgent emotional support, "
                "and use 1177 Vårdguiden for healthcare guidance and where to get care."
            )
            if not therapists:
                coach_message += " Please share a city or postcode so I can look for nearby in-person support options."

            return {
                "route": "FINAL",
                "response_json": ChatResponse(
                    coach_message=coach_message,
                    resources=[
                        Resource(title="Emergency services (Sweden) - 112", url="https://www.112.se/"),
                        Resource(title="Mind Självmordslinjen - 90101", url="https://mind.se/hitta-hjalp/sjalvmordslinjen/"),
                        Resource(title="1177 Vårdguiden", url="https://www.1177.se/"),
                    ],
                    therapists=therapists,
                    risk_level="crisis",
                    premium_cta=None,
                ).model_dump(),
            }

        if contains_jailbreak_attempt(message) or not scope_check(message):
            return {
                "route": "FINAL",
                "response_json": ChatResponse(
                    coach_message=(
                        "I'm here to help with mental health coping skills, finding therapists, or booking appointments. "
                        "I'm not able to help with that — is there something in those areas I can support you with?"
                    ),
                    resources=[],
                    risk_level="out_of_scope",
                ).model_dump(),
            }

        history_lines = [
            f"- {'assistant' if isinstance(item, AIMessage) else 'user'}: {str(item.content)}"
            for item in state["messages"][:-1][-6:]
        ]
        prompt = (
            f"{SAFETY_GATE_MASTER_PROMPT}\n"
            "Return only JSON with keys action, risk_level, coach_message, resources.\n"
            "Use action=stop for crisis, jailbreak, out-of-scope, or prescription/medical advice requests.\n"
            "Use action=continue only when the request should proceed to the supervisor.\n"
            "Short replies of 1-3 words (yes, no, ok, cancel, confirm, sure, okay) are conversational follow-ups in an ongoing session; always use action=continue for these.\n"
            "Ordinary emotions like anxiety, stress, sadness, overwhelm, nervousness, and panic without self-harm intent should continue to the supervisor with risk_level=normal.\n"
            "Requests about finding therapists, therapist recommendations, booking appointments, sending booking emails, contacting therapists, or premium therapist access are in scope and should continue.\n"
            "Examples that should continue: 'please find me a therapist in karlskrona', 'can you find me a therapist?', 'send me an email?', 'book an appointment', 'contact a therapist for me'.\n"
            "Use risk_level=crisis only for self-harm, suicide, immediate danger, or clear inability to stay safe.\n"
            "Use risk_level=medical for prescriptions, medication changes, dosing, or clinical treatment advice.\n"
            "When stopping, produce the full user-facing safety response yourself.\n"
            f"Recent conversation:\n{chr(10).join(history_lines) if history_lines else '- none'}\n"
            f"Latest user message: {message}"
        )
        decision = _structured_decision(prompt, message, SafetyDecision)
        if decision.action == "stop":
            return {
                "route": "FINAL",
                "response_json": ChatResponse(
                    coach_message=decision.coach_message,
                    resources=[Resource(**item.model_dump()) for item in decision.resources],
                    risk_level=decision.risk_level,
                ).model_dump(),
            }
        return {"route": "COACH"}

    return safety_node


def _route_after_safety(state: AgentState) -> str:
    return "finalize" if state.get("route") == "FINAL" else "supervisor"


def make_supervisor_node(context: GraphRuntimeContext):
    def supervisor_node(state: AgentState) -> AgentState:
        has_pending_booking = bool(context.pending_action) or context.pending_expired
        has_pending_therapist_location = bool(context.request and context.request.cookies.get("mh_pending_therapist_query"))
        message = _latest_user_message(state)
        history_lines = [
            f"- {msg['role']}: {msg['content']}"
            for msg in [
                {
                    "role": "assistant" if isinstance(item, AIMessage) else "user",
                    "content": str(item.content),
                }
                for item in state["messages"][:-1]
            ][-6:]
        ]
        prompt = (
            "You are the supervisor for a LangGraph multi-agent mental health application. "
            "Choose exactly one next specialist route for the latest user message. "
            "Valid routes: COACH, THERAPIST_SEARCH, BOOKING_EMAIL. "
            "Return only JSON with key route.\n\n"
            "Routing policy:\n"
            "- BOOKING_EMAIL: appointment email drafting, email drafting/sending, booking confirmations, YES/NO confirmation replies, pending booking follow-ups, missing therapist email/time follow-ups.\n"
            "- THERAPIST_SEARCH: finding providers, therapist recommendations, location follow-ups after being asked for city/postcode, provider search refinement.\n"
            "- COACH: supportive coping conversation, emotional support, grounding, breathing, journaling, general mental wellbeing guidance.\n"
            "- Requests that mention therapist, counsellor, psychologist, psychiatrist, clinic, provider, or a city/location for therapist search should normally route to THERAPIST_SEARCH.\n"
            "- Requests that mention email, appointment, booking, schedule, contact therapist, send a message, reach out, or help me email should normally route to BOOKING_EMAIL.\n"
            "- Standalone YES, NO, confirm, cancel, ok, sure replies always route to BOOKING_EMAIL regardless of pending state — the booking agent handles the no-pending case itself.\n"
            "- If there is pending booking state, route short follow-up replies like yes/no, times, or therapist emails to BOOKING_EMAIL.\n"
            "- If there is pending therapist-location state, route short city/postcode replies to THERAPIST_SEARCH.\n"
            "- Do not choose COACH when the user is clearly continuing a booking or therapist-search workflow.\n\n"
            f"Pending booking state: {'yes' if has_pending_booking else 'no'}\n"
            f"Pending therapist location request: {'yes' if has_pending_therapist_location else 'no'}\n"
            f"Recent conversation:\n{chr(10).join(history_lines) if history_lines else '- none'}\n"
            f"Latest user message: {message}"
        )
        decision = _structured_decision(prompt, message, RouteDecision)
        return {"route": decision.route}

    return supervisor_node


def _route_after_supervisor(state: AgentState) -> str:
    route = state.get("route")
    if route == "THERAPIST_SEARCH":
        return "therapist"
    if route == "BOOKING_EMAIL":
        return "booking_agent"
    return "sentiment_agent"


def build_sentiment_subgraph():
    """Return a compiled LangGraph subgraph for sentiment analysis.

    The subgraph reads ``messages`` from the parent AgentState, makes a single
    structured LLM call, and writes ``sentiment_analysis`` + ``active_node``
    back into the parent state via key-name merging.
    """

    def analyze_node(state: SentimentAgentState) -> SentimentAgentState:
        # _latest_user_message / _latest_ai_message accept any TypedDict with
        # a "messages" key — cast is safe here.
        message = _latest_user_message(state)  # type: ignore[arg-type]
        history_lines = [
            f"- {'assistant' if isinstance(item, AIMessage) else 'user'}: {str(item.content)}"
            for item in state["messages"][:-1][-6:]
        ]
        prompt = (
            "You are the sentiment analysis specialist inside a larger LangGraph mental health system. "
            "Your job is to analyze the user's emotional tone and produce guidance for the coach agent. "
            "Return only JSON matching the required schema.\n\n"
            "Focus on emotional tone, emotional intensity, and what communication style would help most. "
            "You are not the final user-facing coach and should not answer the user directly.\n"
            "Choose one primary_sentiment from: calm, anxious, stressed, sad, overwhelmed, angry, uncertain, hopeful, mixed.\n"
            "Choose one emotional_intensity from: low, medium, high.\n"
            "Choose one support_style from: warm_and_grounding, calm_and_reassuring, gentle_and_validating, steady_and_structured, encouraging_and_forward_looking.\n"
            "Populate user_needs with short phrases like validation, grounding, reassurance, structure, practical_steps, reflection, hope.\n"
            "Populate coach_handoff with 1-2 sentences telling the coach HOW to respond, not WHAT final answer to give.\n"
            f"Recent conversation:\n{chr(10).join(history_lines) if history_lines else '- none'}\n"
            f"Latest user message: {message}"
        )
        decision = _structured_decision(prompt, message, SentimentAnalysis)
        return {
            "active_node": "sentiment_agent",
            "sentiment_analysis": decision.model_dump(),
        }

    g: StateGraph = StateGraph(SentimentAgentState)
    g.add_node("analyze", analyze_node)
    g.add_edge(START, "analyze")
    g.add_edge("analyze", END)
    return g.compile()


def build_coach_subgraph(tools: list[BaseTool]):
    """Return a compiled LangGraph subgraph for coaching.

    The subgraph reads ``messages`` and ``sentiment_analysis`` from the parent
    AgentState (populated by the sentiment subgraph), runs the coach LLM call,
    and loops through tool calls internally before writing the final AI message
    back to the parent state.
    """

    def coach_node(state: CoachAgentState) -> CoachAgentState:
        sentiment = state.get("sentiment_analysis") or {}
        handoff = sentiment.get("coach_handoff", "No sentiment handoff available.")
        support_style = sentiment.get("support_style", "gentle_and_validating")
        primary_sentiment = sentiment.get("primary_sentiment", "mixed")
        emotional_intensity = sentiment.get("emotional_intensity", "medium")
        user_needs = sentiment.get("user_needs", [])
        response = _graph_model_response(
            (
                f"{COACH_MASTER_PROMPT}\n"
                "You are the coach specialist inside a larger LangGraph system. "
                "Another specialist agent has already analyzed the user's sentiment; you must use that handoff to shape your tone and pacing. "
                f"Sentiment agent handoff: primary_sentiment={primary_sentiment}; emotional_intensity={emotional_intensity}; support_style={support_style}; user_needs={', '.join(user_needs) if user_needs else 'none'}; guidance={handoff}. "
                "Use tools when retrieved context would help. "
                "When you are finished, respond naturally as the coaching specialist; final app formatting happens later."
            ),
            state,  # type: ignore[arg-type]
            tools=tools,
        )
        return {"active_node": "coach_agent", "messages": [response]}

    def _coach_route(state: CoachAgentState) -> str:
        msg = _latest_ai_message(state)  # type: ignore[arg-type]
        if msg and msg.tool_calls:
            return "tools"
        return END

    g: StateGraph = StateGraph(CoachAgentState)
    g.add_node("coach", coach_node)
    g.add_node("tools", ToolNode(tools))
    g.add_edge(START, "coach")
    g.add_conditional_edges("coach", _coach_route)
    g.add_edge("tools", "coach")
    return g.compile()


def make_therapist_node(context: GraphRuntimeContext):
    def therapist_node(state: AgentState) -> AgentState:
        if not context.request:
            return {
                "active_node": "therapist",
                "therapist_search": TherapistSearch(status="unavailable", results=[], message=None),
                "response_json": ChatResponse(
                    coach_message="Therapist search is unavailable right now.",
                    therapists=[],
                ).model_dump(),
            }

        therapist_handler = TherapistSearchHandler(
            search_fn=context.therapist_search_fn or mcp_therapist_search,
            dev_mode=settings.dev_mode,
            session_cookie_name=settings.session_cookie_name,
        )
        response = therapist_handler.handle(
            user=context.user,
            request=context.request,
            message=_latest_user_message(state),
        )

        results = [
            item.model_dump() if isinstance(item, TherapistResult) else item
            for item in (response.therapists or [])
        ]
        if response.therapists:
            status = "ok"
        elif response.premium_cta and "sign in" in (response.coach_message or "").lower():
            status = "auth_required"
        elif response.premium_cta and "premium" in (response.coach_message or "").lower():
            status = "premium_required"
        elif response.coach_message and response.coach_message.startswith("Please share a city or postcode"):
            status = "needs_location"
        else:
            status = "no_results"

        return {
            "active_node": "therapist",
            "therapist_search": TherapistSearch(status=status, results=results, message=response.coach_message),
            "response_json": response.model_dump(),
        }

    return therapist_node


def build_booking_subgraph(tools: list[BaseTool], context: GraphRuntimeContext):
    """Return a compiled LangGraph subgraph for booking email handling.

    Flow:
      START → booking ──(tool_calls?)──→ tools ──→ booking
                      ──(done)────────→ format_response → END

    * ``booking_node``         – LLM agent with full tool access; reasons about
                                  pending state, collects missing fields, calls tools.
    * ``format_response_node`` – LLM with structured output (ChatResponse); reads
                                  the full conversation + tool results and produces
                                  the final response JSON.  No Python if/else.

    Both nodes share ``messages``, ``active_node``, and ``response_json`` with the
    parent ``AgentState`` via LangGraph key-name merging.
    """

    def booking_node(state: BookingAgentState) -> dict:
        pending_state = "pending_exists" if context.pending_action or context.pending_expired else "no_pending"
        prompt = (
            f"{BOOKING_EMAIL_MASTER_PROMPT}\n"
            "You are the booking specialist inside a larger LangGraph multi-agent system.\n"
            f"Pending booking state at session start: {pending_state}.\n\n"
            "MANDATORY DECISION TREE — follow exactly, in order:\n"
            "1. ALWAYS call load_pending_booking first.\n"
            "2. Read the tool result status field, then act:\n"
            "   status=PENDING_READY + user message contains YES/confirm/ok/sure/yep/yeah/send it:\n"
            "       → YOU MUST call send_pending_booking_email immediately. Do NOT ask again.\n"
            "   status=PENDING_READY + user message contains NO/cancel/nope/don't/stop:\n"
            "       → call cancel_pending_booking.\n"
            "   status=PENDING_READY + user provides NEW therapist email or datetime:\n"
            "       → call prepare_booking_from_message to update the pending.\n"
            "   status=PENDING_READY + no clear user action yet:\n"
            "       → summarise the pending booking and ask user to confirm or cancel.\n"
            "   status=NO_PENDING + user provides therapist email and/or datetime:\n"
            "       → call prepare_booking_from_message.\n"
            "   status=NO_PENDING + user says YES/confirm without providing details:\n"
            "       → do NOT call any send/prepare tool. Explain there is no pending booking and ask for therapist email and date/time.\n"
            "   status=EXPIRED:\n"
            "       → do NOT call send_pending_booking_email. Explain the booking expired and offer to start over.\n"
            "3. Always follow the action_hint field in the tool result.\n"
            "Respond naturally; a separate formatter produces the final structured JSON."
        )
        response = _graph_model_response(prompt, state, tools=tools)  # type: ignore[arg-type]
        return {"active_node": "booking_agent", "messages": [response]}

    def _booking_route(state: BookingAgentState) -> str:
        msg = _latest_ai_message(state)  # type: ignore[arg-type]
        if msg and msg.tool_calls:
            return "tools"
        return "format_response"

    def format_response_node(state: BookingAgentState) -> dict:
        """LLM with structured output: reads the full conversation + tool results
        and returns a complete ChatResponse.  This is still LLM reasoning —
        just schema-constrained output rather than free-form text."""
        model = get_langchain_chat_model(temperature=0)
        structured = model.with_structured_output(ChatResponse)
        prompt = (
            "You are the response formatter for a booking specialist agent.\n"
            "Read the full conversation (including all tool call results) and produce a ChatResponse.\n\n"
            "Priority rules (check in this order):\n"
            "1. If send_pending_booking_email returned ok=true → coach_message confirms email was sent, requires_confirmation=false, booking_proposal=null.\n"
            "2. If send_pending_booking_email returned ok=false with 'expired' in error → coach_message explains expiry, requires_confirmation=false, booking_proposal=null.\n"
            "3. If load_pending_booking returned status=EXPIRED → coach_message explains booking expired, requires_confirmation=false, booking_proposal=null.\n"
            "4. If cancel_pending_booking returned ok=true → coach_message confirms cancellation, requires_confirmation=false, booking_proposal=null.\n"
            "5. If prepare_booking_from_message returned ok=true AND the payload has NON-NULL therapist_email, subject, AND body → requires_confirmation=true, set booking_proposal with all four fields (therapist_email, requested_time from payload.requested_datetime_iso, subject, body) and expires_at, coach_message asks the user to confirm sending.\n"
            "   CRITICAL: Only set requires_confirmation=true for rule 5 if ALL three fields (therapist_email, subject, body) are present and non-null. If any is null/missing, use rule 7 instead.\n"
            "6. If load_pending_booking returned status=PENDING_READY and the payload has NON-NULL therapist_email, subject, AND body, and no send/cancel/prepare happened → requires_confirmation=true, populate booking_proposal, coach_message asks user to confirm or cancel.\n"
            "   CRITICAL: Only use rule 6 if therapist_email, subject, and body are all non-null in the payload.\n"
            "7. If information is still missing (therapist email not yet provided, or date/time not yet provided, or subject/body could not be built) → requires_confirmation=false, booking_proposal=null, coach_message asks only for the specific missing field(s).\n"
            "8. If load_pending_booking returned status=NO_PENDING and no prepare was called → requires_confirmation=false, booking_proposal=null, coach_message explains no pending booking exists and asks for therapist email and date/time.\n"
            "Never set booking_proposal unless you have non-null values for therapist_email, requested_time, subject, and body.\n"
            "Never invent booking details not present in tool output.\n"
            "Set risk_level=normal unless the conversation indicates otherwise."
        )
        try:
            result = structured.invoke([SystemMessage(content=prompt), *state["messages"]])
            if isinstance(result, ChatResponse):
                return {"active_node": "booking_agent", "response_json": result.model_dump()}
            if isinstance(result, dict):
                return {"active_node": "booking_agent", "response_json": ChatResponse.model_validate(result).model_dump()}
        except Exception:
            # Pydantic validation or LLM parsing failed (e.g. LLM tried to set
            # booking_proposal with null required fields).  Return a safe fallback.
            return {
                "active_node": "booking_agent",
                "response_json": ChatResponse(
                    coach_message="I need a few more details. Could you provide the therapist's email and preferred date/time for the appointment?",
                    requires_confirmation=False,
                ).model_dump(),
            }
        return {}

    g: StateGraph = StateGraph(BookingAgentState)
    g.add_node("booking", booking_node)
    g.add_node("tools", ToolNode(tools))
    g.add_node("format_response", format_response_node)
    g.add_edge(START, "booking")
    g.add_conditional_edges("booking", _booking_route)
    g.add_edge("tools", "booking")
    g.add_edge("format_response", END)
    return g.compile()


def make_finalize_node(_context: GraphRuntimeContext):
    def finalize_node(state: AgentState) -> AgentState:
        # Therapist and safety nodes set response_json directly; pass through.
        if state.get("response_json"):
            return {"response_json": state["response_json"]}
        # Coach and booking nodes produce messages; use LLM to structure them.
        prompt = (
            "You are the final response formatter for a LangGraph mental health application.\n"
            "Return only a ChatResponse object using the full conversation and any tool outputs already present in the messages.\n"
            "Map therapist search outcomes into therapists and premium_cta fields.\n"
            "Map booking proposal state into booking_proposal and requires_confirmation fields.\n"
            "Map send/cancel/expired booking outcomes into coach_message and requires_confirmation=false.\n"
            "Map crisis or medical safety outcomes into risk_level/resources as appropriate.\n"
            "Never invent therapist entities that are not grounded in tool output.\n"
            "Do not invent fields; only populate what the conversation and tool outputs support."
        )
        payload = _structured_chat_response(prompt, state)
        return {"response_json": payload}

    return finalize_node


def build_graph(
    context: GraphRuntimeContext | None = None,
    retrieve_fn: Callable[[AgentState], AgentState] | None = None,
    llm_fn: Callable[[AgentState], AgentState] | None = None,
):
    if retrieve_fn or llm_fn:
        return _legacy_build_graph(retrieve_fn=retrieve_fn, llm_fn=llm_fn)
    runtime_context = context or GraphRuntimeContext()
    coach_tools, booking_tools = _build_tools(runtime_context)
    graph = StateGraph(AgentState)
    graph.add_node("safety", make_safety_node(runtime_context))
    graph.add_node("supervisor", make_supervisor_node(runtime_context))
    # True subgraphs — each has its own compiled StateGraph with START/END cycle
    graph.add_node("sentiment_agent", build_sentiment_subgraph())
    graph.add_node("coach_agent", build_coach_subgraph(coach_tools))
    graph.add_node("booking_agent", build_booking_subgraph(booking_tools, runtime_context))
    # Deterministic handler node — no LLM loop; writes therapist_search + response_json into state
    graph.add_node("therapist", make_therapist_node(runtime_context))
    graph.add_node("finalize", make_finalize_node(runtime_context))
    graph.add_edge(START, "safety")
    graph.add_conditional_edges("safety", _route_after_safety)
    graph.add_conditional_edges("supervisor", _route_after_supervisor)
    # Sentiment output flows directly into coach; both tool loops are encapsulated inside their subgraphs
    graph.add_edge("sentiment_agent", "coach_agent")
    graph.add_edge("coach_agent", "finalize")
    # Therapist sets response_json directly — direct edge to finalize, no tool wiring needed
    graph.add_edge("therapist", "finalize")
    graph.add_edge("booking_agent", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


async def arun_agent(
    message: str,
    history: list[dict[str, str]] | None = None,
    context: GraphRuntimeContext | None = None,
    retrieve_fn: Callable[[AgentState], AgentState] | None = None,
    llm_fn: Callable[[AgentState], AgentState] | None = None,
) -> dict[str, Any]:
    graph = build_graph(context=context, retrieve_fn=retrieve_fn, llm_fn=llm_fn)
    state = await graph.ainvoke({"messages": _history_to_messages(history, message)})
    return state.get("response_json", {})


def run_agent(
    message: str,
    history: list[dict[str, str]] | None = None,
    context: GraphRuntimeContext | None = None,
    retrieve_fn: Callable[[AgentState], AgentState] | None = None,
    llm_fn: Callable[[AgentState], AgentState] | None = None,
) -> dict[str, Any]:
    return asyncio.run(
        arun_agent(
            message=message,
            history=history,
            context=context,
            retrieve_fn=retrieve_fn,
            llm_fn=llm_fn,
        )
    )

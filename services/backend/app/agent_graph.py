from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Callable, Literal, TypedDict

from fastapi import HTTPException
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field
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
from .llm.langchain_model import get_langchain_chat_model
from .llm.provider import ProviderError, ProviderNotConfiguredError, generate_chat
from .mcp_client import ainvoke_mcp_tool, mcp_therapist_search
from .models import PendingAction, User
from .prompts import (
    BOOKING_EMAIL_MASTER_PROMPT,
    COACH_MASTER_PROMPT,
    SAFETY_GATE_MASTER_PROMPT,
    THERAPIST_SEARCH_MASTER_PROMPT,
)
from .safety import is_crisis
from .schemas import ChatResponse, PremiumCta, Resource, TherapistResult


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    route: Literal["COACH", "THERAPIST_SEARCH", "BOOKING_EMAIL", "FINAL"]
    retrieved_chunks: list[dict[str, Any]]
    response_json: dict[str, Any]


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
    therapist_search_status: str | None = None
    therapist_search_results: list[dict[str, Any]] = field(default_factory=list)
    therapist_search_message: str | None = None


class SafetyDecision(BaseModel):
    action: Literal["continue", "stop"]
    risk_level: Literal["normal", "crisis", "jailbreak", "medical", "out_of_scope"]
    coach_message: str = ""
    resources: list[dict[str, str]] = Field(default_factory=list)


class RouteDecision(BaseModel):
    route: Literal["COACH", "THERAPIST_SEARCH", "BOOKING_EMAIL"]


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


def _build_tools(context: GraphRuntimeContext) -> tuple[list[BaseTool], list[BaseTool], list[BaseTool]]:
    def retrieve_context_tool_impl(query: str) -> list[dict[str, Any]]:
        if not pgvector_ready():
            return []
        try:
            return retrieve_similar_chunks(query, top_k=4)
        except ProviderNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    async def therapist_search_tool_impl(
        location_text: str,
        radius_km: int = 25,
        specialty: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        user = context.user
        if not user:
            context.therapist_search_status = "auth_required"
            context.therapist_search_results = []
            context.therapist_search_message = "Please sign in to use therapist search."
            return [{"status": "auth_required", "message": context.therapist_search_message}]
        if not user.is_premium:
            context.therapist_search_status = "premium_required"
            context.therapist_search_results = []
            context.therapist_search_message = "Therapist search is available with premium access."
            return [{"status": "premium_required", "message": context.therapist_search_message}]
        payload: dict[str, Any] = {
            "location_text": location_text,
            "radius_km": min(max(radius_km, 1), 50),
            "limit": min(max(limit, 1), 10),
        }
        if specialty:
            payload["specialty"] = specialty
        try:
            results = await ainvoke_mcp_tool("therapist_search_tool", payload)
        except Exception:
            context.therapist_search_status = "error"
            context.therapist_search_results = []
            context.therapist_search_message = "Therapist search failed. Please try again."
            return [{"status": "error", "message": context.therapist_search_message}]
        if not isinstance(results, list):
            context.therapist_search_status = "error"
            context.therapist_search_results = []
            context.therapist_search_message = "Therapist search failed. Please try again."
            return [{"status": "error", "message": context.therapist_search_message}]
        normalized_results = [item for item in results if isinstance(item, dict)]
        context.therapist_search_results = normalized_results
        if normalized_results:
            context.therapist_search_status = "ok"
            context.therapist_search_message = None
            return normalized_results
        context.therapist_search_status = "no_results"
        context.therapist_search_message = "I couldn't find therapists matching that search. Try a broader area or a different specialty."
        return [{"status": "no_results", "message": context.therapist_search_message}]

    def load_pending_booking_tool_impl() -> dict[str, Any]:
        if not context.db or not context.actor_key:
            return {"pending": False, "expired": context.pending_expired}
        pending_action, expired = load_pending_booking(context.db, context.actor_key)
        context.pending_action = pending_action
        context.pending_expired = expired
        if not pending_action:
            return {"pending": False, "expired": expired}
        return {
            "pending": True,
            "expired": expired,
            "payload": parse_pending_payload(pending_action),
            "expires_at": pending_action.expires_at.isoformat(),
        }

    def prepare_booking_from_message_tool_impl(message: str) -> dict[str, Any]:
        if not context.db or not context.actor_key:
            return {"ok": False, "error": "Booking is unavailable right now."}
        extracted = extract_booking_data(message)
        payload: dict[str, Any] = {
            "therapist_email": extracted.therapist_email,
            "requested_datetime_iso": extracted.requested_datetime.isoformat() if extracted.requested_datetime else None,
            "subject": None,
            "body": None,
            "reply_to": context.user.email if context.user and context.user.email else None,
            "sender_name": extracted.sender_name or (context.user.name if context.user and context.user.name else None),
            "clarification": extracted.clarification,
        }
        if extracted.therapist_email and extracted.requested_datetime:
            payload = build_booking_email_content(
                user=context.user,
                therapist_email=extracted.therapist_email,
                requested_datetime=extracted.requested_datetime,
                sender_name=extracted.sender_name,
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
    therapist_search_tool = StructuredTool.from_function(
        coroutine=therapist_search_tool_impl,
        name="therapist_search",
        description="Search nearby therapists, psychologists, clinics, and counsellors.",
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

    return [retrieve_context_tool], [therapist_search_tool], [load_pending_booking_tool, prepare_booking_from_message_tool, send_pending_booking_email_tool, cancel_pending_booking_tool]


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
        history_lines = [
            f"- {'assistant' if isinstance(item, AIMessage) else 'user'}: {str(item.content)}"
            for item in state["messages"][:-1][-6:]
        ]
        prompt = (
            f"{SAFETY_GATE_MASTER_PROMPT}\n"
            "Return only JSON with keys action, risk_level, coach_message, resources.\n"
            "Use action=stop for crisis, jailbreak, out-of-scope, or prescription/medical advice requests.\n"
            "Use action=continue only when the request should proceed to the supervisor.\n"
            "Ordinary emotions like anxiety, stress, sadness, overwhelm, nervousness, and panic without self-harm intent should continue to the supervisor with risk_level=normal.\n"
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
                    resources=[Resource(**item) for item in decision.resources],
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
        return "therapist_agent"
    if route == "BOOKING_EMAIL":
        return "booking_agent"
    return "coach_agent"


def make_coach_agent_node(tools: list[BaseTool]):
    def coach_agent(state: AgentState) -> AgentState:
        response = _graph_model_response(
            (
                f"{COACH_MASTER_PROMPT}\n"
                "You are the coach specialist inside a larger LangGraph system. "
                "Use tools when retrieved context would help. "
                "When you are finished, respond naturally as the coaching specialist; final app formatting happens later."
            ),
            state,
            tools=tools,
        )
        return {"messages": [response]}

    return coach_agent


def make_therapist_agent_node(tools: list[BaseTool], context: GraphRuntimeContext):
    def therapist_agent(state: AgentState) -> AgentState:
        premium_state = "premium" if (context.user and context.user.is_premium) or settings.dev_mode else "not_premium"
        auth_state = "signed_in" if context.user else "anonymous"
        prompt = (
            f"{THERAPIST_SEARCH_MASTER_PROMPT}\n"
            "You are the therapist search specialist inside a larger LangGraph system.\n"
            "You must reason as the therapist search agent, not as a general coach.\n"
            f"Auth state: {auth_state}. Access state: {premium_state}.\n"
            "If the user is asking to find therapists and a location is present, you must call the therapist_search tool before answering.\n"
            "Use the therapist_search tool when you have enough search information.\n"
            "If location is missing, ask only for city or postcode.\n"
            "If the tool reports sign-in or premium access errors, clearly explain that sign-in or premium access is required.\n"
            "If results exist, clearly summarize them for the user.\n"
            "Never invent therapist names, addresses, phones, emails, or URLs.\n"
            "If no concrete therapist rows are returned by the tool, do not mention any concrete therapists.\n"
            "Respond as the therapist search specialist; final app formatting happens later."
        )
        response = _graph_model_response(prompt, state, tools=tools)
        return {"messages": [response]}

    return therapist_agent


def make_booking_agent_node(tools: list[BaseTool], context: GraphRuntimeContext):
    def booking_agent(state: AgentState) -> AgentState:
        pending_state = "pending_exists" if context.pending_action or context.pending_expired else "no_pending"
        prompt = (
            f"{BOOKING_EMAIL_MASTER_PROMPT}\n"
            "You are the booking specialist inside a larger LangGraph system.\n"
            f"Pending booking state at entry: {pending_state}.\n"
            "Always call load_pending_booking first before deciding what to do.\n"
            "If the user is starting or continuing a booking workflow, stay in booking mode.\n"
            "If there is no pending request and the user says YES/NO/confirm/cancel, return guidance that no pending booking exists.\n"
            "Use prepare_booking_from_message to parse and persist proposal state.\n"
            "Use send_pending_booking_email only after explicit confirmation.\n"
            "Use cancel_pending_booking when the user declines or cancels.\n"
            "When information is missing, ask only for the missing fields.\n"
            "Respond as the booking specialist; final app formatting happens later."
        )
        response = _graph_model_response(prompt, state, tools=tools)
        return {"messages": [response]}

    return booking_agent


def _tool_route_for(node_name: str, tool_node_name: str):
    def route(state: AgentState) -> str:
        if state.get("response_json"):
            return "finalize"
        message = _latest_ai_message(state)
        if message and message.tool_calls:
            return tool_node_name
        return "finalize"

    return route


def make_finalize_node(context: GraphRuntimeContext):
    def finalize_node(state: AgentState) -> AgentState:
        if state.get("response_json"):
            return {"response_json": state["response_json"]}
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
        if state.get("route") == "THERAPIST_SEARCH":
            status = context.therapist_search_status
            grounded = ChatResponse.model_validate(payload)
            if status == "ok":
                grounded.therapists = [TherapistResult.model_validate(item) for item in context.therapist_search_results]
                grounded.premium_cta = None
            else:
                grounded.therapists = None
                if status in {"auth_required", "premium_required"}:
                    grounded.premium_cta = PremiumCta(enabled=True, message=context.therapist_search_message or "Premium access is required.")
                    grounded.coach_message = context.therapist_search_message or grounded.coach_message
                elif status is None and not context.user:
                    grounded.premium_cta = PremiumCta(enabled=True, message="Please sign in to use therapist search.")
                    grounded.coach_message = "Please sign in to use therapist search."
                elif status is None and context.user and not context.user.is_premium:
                    grounded.premium_cta = PremiumCta(enabled=True, message="Therapist search is available with premium access.")
                    grounded.coach_message = "Therapist search is available with premium access."
                elif status in {"no_results", "error"} and context.therapist_search_message:
                    grounded.coach_message = context.therapist_search_message
            payload = grounded.model_dump()
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
    coach_tools, therapist_tools, booking_tools = _build_tools(runtime_context)
    graph = StateGraph(AgentState)
    graph.add_node("safety", make_safety_node(runtime_context))
    graph.add_node("supervisor", make_supervisor_node(runtime_context))
    graph.add_node("coach_agent", make_coach_agent_node(coach_tools))
    graph.add_node("coach_tools", ToolNode(coach_tools))
    graph.add_node("therapist_agent", make_therapist_agent_node(therapist_tools, runtime_context))
    graph.add_node("therapist_tools", ToolNode(therapist_tools))
    graph.add_node("booking_agent", make_booking_agent_node(booking_tools, runtime_context))
    graph.add_node("booking_tools", ToolNode(booking_tools))
    graph.add_node("finalize", make_finalize_node(runtime_context))
    graph.add_edge(START, "safety")
    graph.add_conditional_edges("safety", _route_after_safety)
    graph.add_conditional_edges("supervisor", _route_after_supervisor)
    graph.add_conditional_edges("coach_agent", _tool_route_for("coach_agent", "coach_tools"))
    graph.add_edge("coach_tools", "coach_agent")
    graph.add_conditional_edges("therapist_agent", _tool_route_for("therapist_agent", "therapist_tools"))
    graph.add_edge("therapist_tools", "therapist_agent")
    graph.add_conditional_edges("booking_agent", _tool_route_for("booking_agent", "booking_tools"))
    graph.add_edge("booking_tools", "booking_agent")
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

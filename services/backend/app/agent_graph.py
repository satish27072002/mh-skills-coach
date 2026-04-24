from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Callable, Literal, TypedDict

from fastapi import HTTPException
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel
from sqlalchemy.orm import Session
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

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
    TherapistSearchParams,
    extract_location,
    extract_location_from_short_reply,
    extract_limit,
    extract_radius_km,
    extract_specialty,
    normalize_specialty,
)
from .agents.booking_agent import (
    _booking_proposal_from_payload,
    _missing_booking_fields_message,
    _pending_payload_complete,
)
from .llm.langchain_model import get_langchain_chat_model
from .llm.provider import FALLBACK_COACH_MESSAGE, ProviderError, ProviderNotConfiguredError
from .mcp_client import ainvoke_mcp_tool, mcp_therapist_search
from .models import User
from .persistence import DatabaseCheckpointSaver
from .prompts import (
    BOOKING_EMAIL_MASTER_PROMPT,
    COACH_MASTER_PROMPT,
    SAFETY_GATE_MASTER_PROMPT,
)
from .safety import contains_jailbreak_attempt, is_crisis, is_prescription_request, scope_check
from .schemas import ChatResponse, Resource, TherapistResult


class TherapistSearch(TypedDict, total=False):
    """Typed output contract written by the therapist node into graph state."""
    status: str  # "ok" | "auth_required" | "premium_required" | "needs_location" | "no_results" | "error" | "unavailable"
    results: list[dict[str, Any]]
    message: str | None


class TherapistSession(TypedDict, total=False):
    remembered_location: str | None
    pending_query: dict[str, Any] | None


class BookingSession(TypedDict, total=False):
    status: str
    pending: bool
    expired: bool
    payload: dict[str, Any]
    expires_at: str | None


class BookingAgentState(TypedDict, total=False):
    """State for the booking subgraph — shares messages/active_node/response_json with parent."""
    messages: Annotated[list[AnyMessage], add_messages]
    active_node: str
    response_json: dict[str, Any]
    booking_session: BookingSession


class TherapistAgentState(TypedDict, total=False):
    """State for the therapist subgraph.

    Shared keys (flow in and out via LangGraph key-name merging):
      messages, therapist_session, therapist_search, active_node, response_json

    Internal-only key (not present in AgentState, stays inside the subgraph):
      _search_params — pre-extracted search parameters set by guard_node; absent
                       from AgentState so it is always fresh on each invocation
                       and is silently dropped when merged back to the parent.
    """
    messages: Annotated[list[AnyMessage], add_messages]
    therapist_session: TherapistSession
    therapist_search: TherapistSearch
    active_node: str
    response_json: dict[str, Any]
    _search_params: dict[str, Any]  # internal: {location, radius_km, specialty, limit}


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    route: Literal["COACH", "THERAPIST_SEARCH", "BOOKING_EMAIL", "FINAL"]
    active_node: str
    sentiment_analysis: dict[str, Any]
    therapist_session: TherapistSession
    therapist_search: TherapistSearch
    booking_session: BookingSession
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
    request: Any | None = None
    therapist_search_fn: Callable[[str, int | None, str | None, int], list[Any]] | None = None
    send_email_fn: Callable[[str, EmailSendPayload], dict[str, Any]] | None = None


_GRAPH_CHECKPOINTER = DatabaseCheckpointSaver()

# Per-request context — set once in arun_agent so that node functions and tool
# closures can access the DB session, user, etc. without the graph being rebuilt
# on every request.  ContextVar is automatically propagated to child asyncio tasks.
_REQUEST_CONTEXT: ContextVar[GraphRuntimeContext] = ContextVar("_request_context")


def _get_ctx() -> GraphRuntimeContext:
    """Return the runtime context for the current request.

    Falls back to an empty (no-op) context so that unit tests that call
    run_agent / build_graph without an explicit context still work.
    """
    try:
        return _REQUEST_CONTEXT.get()
    except LookupError:
        return GraphRuntimeContext()


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


def _tool_message_payload(message: ToolMessage) -> Any:
    content = message.content
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text") or ""))
            else:
                text_parts.append(str(item))
        content = "\n".join(part for part in text_parts if part)
    if isinstance(content, str):
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1])
        try:
            return json.loads(text)
        except Exception:
            return text
    return content


def _latest_tool_result(state: BookingAgentState, tool_name: str) -> Any | None:
    messages = state["messages"]
    last_human_index = -1
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            last_human_index = index
            break
    search_space = messages[last_human_index + 1 :] if last_human_index >= 0 else messages
    for message in reversed(search_space):
        if isinstance(message, ToolMessage) and getattr(message, "name", None) == tool_name:
            return _tool_message_payload(message)
    return None


def _expires_at_from_result(result: dict[str, Any]) -> datetime:
    expires_at = result.get("expires_at")
    if isinstance(expires_at, str):
        try:
            return datetime.fromisoformat(expires_at)
        except ValueError:
            pass
    return datetime.now()


def _current_booking_session(context: GraphRuntimeContext) -> BookingSession:
    if not context.db or not context.actor_key:
        return {"status": "NO_PENDING", "pending": False, "expired": False, "payload": {}, "expires_at": None}
    pending_action, expired = load_pending_booking(context.db, context.actor_key)
    if expired:
        return {"status": "EXPIRED", "pending": False, "expired": True, "payload": {}, "expires_at": None}
    if not pending_action:
        return {"status": "NO_PENDING", "pending": False, "expired": False, "payload": {}, "expires_at": None}
    payload = parse_pending_payload(pending_action)
    return {
        "status": "PENDING_READY",
        "pending": True,
        "expired": False,
        "payload": payload,
        "expires_at": pending_action.expires_at.isoformat(),
    }


def _trim_history_node(state: AgentState) -> AgentState:
    """Bound the checkpointed message history.

    LangGraph's ``add_messages`` reducer is append-only, so without a trim
    step the persisted ``messages`` list grows every turn forever.  That
    inflates every subsequent prompt, bloats the Postgres checkpoint table,
    and eventually overflows the model's context window.

    This node reads ``state["messages"]`` and — if the count exceeds
    ``settings.graph_message_window`` — returns ``RemoveMessage`` entries for
    the oldest surplus messages.  The reducer applies RemoveMessage before
    any subsequent node appends, so downstream nodes always see a trimmed
    view and the persisted state never exceeds the window.
    """
    messages = state.get("messages") or []
    window = settings.graph_message_window
    # LangGraph requires every node to write at least one state key, so we
    # always set active_node even when there's nothing to trim.
    if len(messages) <= window:
        return {"active_node": "trim_history"}
    to_drop = messages[:-window]
    removes: list[AnyMessage] = []
    for msg in to_drop:
        msg_id = getattr(msg, "id", None)
        if msg_id:
            removes.append(RemoveMessage(id=msg_id))
    if not removes:
        return {"active_node": "trim_history"}
    return {"active_node": "trim_history", "messages": removes}


def _session_state_node(_state: AgentState) -> AgentState:
    """Load per-request booking state into the graph before the supervisor runs."""
    return {"booking_session": _current_booking_session(_get_ctx())}


# ---------------------------------------------------------------------------
# LLM resilience — retry + fallback for all graph LLM calls.
#
# The LangChain model.invoke can raise a variety of exceptions (httpx errors,
# openai.APIError subclasses, etc.).  We normalize them into ProviderError so
# tenacity can retry on a single type, and so the outer layer can distinguish
# transient-LLM failures from programmer errors (which we never want to retry).
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


_GRAPH_LLM_RETRY = retry(
    retry=retry_if_exception_type(ProviderError),
    stop=stop_after_attempt(settings.llm_max_retries),
    wait=wait_exponential(multiplier=1, min=2, max=8),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)


def _wrap_as_provider_error(exc: BaseException, op: str) -> ProviderError:
    """Wrap a non-provider exception as a retryable ProviderError."""
    return ProviderError(f"{op} failed: {type(exc).__name__}: {exc}")


def _safe_default_decision(model_cls: type[BaseModel]) -> BaseModel:
    """Conservative defaults returned when a structured decision LLM call is
    exhausted.  Each default is chosen to keep the user safe and the graph
    flowing to a user-visible fallback message.
    """
    if model_cls is RouteDecision:
        # Coach is the safest route on LLM failure — no external tool calls,
        # the coach node will itself return the fallback message.
        return RouteDecision(route="COACH")
    if model_cls is SafetyDecision:
        # Can't assess risk → stop politely.  Deterministic is_crisis /
        # is_prescription_request checks run BEFORE this in _safety_node,
        # so real crises are already handled by the time we reach here.
        return SafetyDecision(
            action="stop",
            risk_level="normal",
            coach_message=FALLBACK_COACH_MESSAGE,
            resources=[],
        )
    if model_cls is SentimentAnalysis:
        return SentimentAnalysis(
            primary_sentiment="mixed",
            emotional_intensity="medium",
            support_style="gentle_and_validating",
            user_needs=["validation"],
            coach_handoff="Respond with gentle validation and keep it short.",
        )
    raise ProviderError(f"No safe default for model_cls={model_cls.__name__}")


@_GRAPH_LLM_RETRY
def _invoke_chat_with_tools(
    model: Any, tools: list[BaseTool], messages: list[AnyMessage]
) -> AIMessage:
    """Inner retry-wrapped call to bind tools and invoke the chat model."""
    try:
        bound = model.bind_tools(tools)
        response = bound.invoke(messages)
    except (ProviderError, ProviderNotConfiguredError):
        raise
    except Exception as exc:  # network, openai.APIError, etc.
        raise _wrap_as_provider_error(exc, "graph chat invoke") from exc
    if not isinstance(response, AIMessage):
        return AIMessage(content=str(getattr(response, "content", response)))
    return response


def _graph_model_response(system_prompt: str, state: AgentState, *, tools: list[BaseTool]) -> AIMessage:
    """Public entrypoint for coach/booking LLM calls inside the graph.

    Retries on transient errors (tenacity, llm_max_retries attempts, 2s–8s
    exponential backoff).  On final exhaustion returns an AIMessage containing
    FALLBACK_COACH_MESSAGE so the graph can still flow to finalize.
    """
    model = get_langchain_chat_model()
    messages: list[AnyMessage] = [SystemMessage(content=system_prompt), *state["messages"]]
    try:
        return _invoke_chat_with_tools(model, tools, messages)
    except (ProviderError, ProviderNotConfiguredError) as exc:
        logger.error(
            "_graph_model_response: retries exhausted, returning fallback AIMessage. error=%s",
            exc,
        )
        return AIMessage(content=FALLBACK_COACH_MESSAGE)


@_GRAPH_LLM_RETRY
def _invoke_structured_chat(model_structured: Any, messages: list[AnyMessage]) -> ChatResponse:
    """Inner retry-wrapped structured ChatResponse call."""
    try:
        result = model_structured.invoke(messages)
    except (ProviderError, ProviderNotConfiguredError):
        raise
    except Exception as exc:
        raise _wrap_as_provider_error(exc, "structured chat invoke") from exc
    if isinstance(result, ChatResponse):
        return result
    if isinstance(result, dict):
        return ChatResponse.model_validate(result)
    raise ProviderError("structured chat response parsing failed")


def _structured_chat_response(prompt: str, state: AgentState) -> dict[str, Any]:
    """Public entrypoint for _finalize_node's structured ChatResponse call.

    Retries on transient errors; on exhaustion returns a safe ChatResponse
    dict containing FALLBACK_COACH_MESSAGE.
    """
    model = get_langchain_chat_model(temperature=0)
    structured = model.with_structured_output(ChatResponse)
    messages: list[AnyMessage] = [SystemMessage(content=prompt), *state["messages"]]
    try:
        return _invoke_structured_chat(structured, messages).model_dump()
    except (ProviderError, ProviderNotConfiguredError) as exc:
        logger.error(
            "_structured_chat_response: retries exhausted, returning fallback ChatResponse. error=%s",
            exc,
        )
        return ChatResponse(
            coach_message=FALLBACK_COACH_MESSAGE,
            risk_level="normal",
        ).model_dump()


@_GRAPH_LLM_RETRY
def _invoke_structured_decision(
    model_structured: Any, messages: list[AnyMessage], model_cls: type[BaseModel]
) -> BaseModel:
    """Inner retry-wrapped call for any structured BaseModel decision."""
    try:
        result = model_structured.invoke(messages)
    except (ProviderError, ProviderNotConfiguredError):
        raise
    except Exception as exc:
        raise _wrap_as_provider_error(exc, f"structured decision ({model_cls.__name__})") from exc
    if isinstance(result, model_cls):
        return result
    if isinstance(result, dict):
        return model_cls.model_validate(result)
    raise ProviderError("structured decision parsing failed")


def _structured_decision(prompt: str, message: str, model_cls: type[BaseModel]) -> BaseModel:
    """Public entrypoint for supervisor/safety/sentiment structured decisions.

    Retries on transient errors; on exhaustion returns a conservative default
    via _safe_default_decision() so the graph never 500s on an LLM outage.
    """
    model = get_langchain_chat_model(temperature=0)
    structured = model.with_structured_output(model_cls)
    messages: list[AnyMessage] = [
        SystemMessage(content=prompt),
        HumanMessage(content=message),
    ]
    try:
        return _invoke_structured_decision(structured, messages, model_cls)
    except (ProviderError, ProviderNotConfiguredError) as exc:
        logger.error(
            "_structured_decision: retries exhausted for %s, returning safe default. error=%s",
            model_cls.__name__,
            exc,
        )
        return _safe_default_decision(model_cls)


def _build_tools() -> tuple[list[BaseTool], list[BaseTool]]:
    """Build tools once at module load.  Each tool reads the current request context
    via _get_ctx() at call time — no context parameter needed at build time.
    """

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
        context = _get_ctx()
        if not context.db or not context.actor_key:
            return {
                "status": "NO_PENDING",
                "pending": False,
                "expired": False,
                "action_hint": "No pending booking exists. Ask the user for therapist email and preferred date/time.",
            }

        pending_action, db_expired = load_pending_booking(context.db, context.actor_key)
        if db_expired:
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
        context = _get_ctx()
        if not context.db or not context.actor_key:
            return {"ok": False, "error": "Booking is unavailable right now."}
        extracted = extract_booking_data(message)

        # Merge with any existing partial pending so multi-turn works correctly.
        existing_payload: dict[str, Any] = {}
        existing_pending, _ = load_pending_booking(context.db, context.actor_key)
        if existing_pending:
            existing_payload = parse_pending_payload(existing_pending)

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
        return {
            "ok": True,
            "payload": payload,
            "expires_at": pending.expires_at.isoformat(),
            "ttl_minutes": BOOKING_TTL_MINUTES,
        }

    async def send_pending_booking_email_tool_impl() -> dict[str, Any]:
        context = _get_ctx()
        if not context.db or not context.actor_key:
            return {"ok": False, "error": "Booking is unavailable right now."}
        pending_action, expired = load_pending_booking(context.db, context.actor_key)
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
        return {"ok": True, "message": "Email sent successfully.", "result": result}

    def cancel_pending_booking_tool_impl() -> dict[str, Any]:
        context = _get_ctx()
        if not context.db or not context.actor_key:
            return {"ok": False, "error": "Booking is unavailable right now."}
        pending_action, _ = load_pending_booking(context.db, context.actor_key)
        if not pending_action:
            return {"ok": False, "error": "No pending booking to cancel."}
        clear_pending_booking(context.db, pending_action)
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


def _safety_node(state: AgentState) -> AgentState:
        message = _latest_user_message(state)
        therapist_session = state.get("therapist_session") or {}

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

            _ctx = _get_ctx()
            if _ctx.request is not None:
                location = extract_location(message) or therapist_session.get("remembered_location")
                radius_km = extract_radius_km(message) or 25

            if location:
                therapist_agent = TherapistSearchHandler(
                    search_fn=_ctx.therapist_search_fn or mcp_therapist_search,
                    dev_mode=True,
                    session_cookie_name=settings.session_cookie_name,
                )
                results, _ = therapist_agent.search_with_retries(
                    location_text=location,
                    radius_km=radius_km,
                    specialty=specialty,
                )
                therapists = [TherapistResult.model_validate(item) for item in results]

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
                "therapist_session": {
                    "remembered_location": location or therapist_session.get("remembered_location"),
                    "pending_query": None,
                },
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


def _route_after_safety(state: AgentState) -> str:
    # Safety sets response_json and route=FINAL for crisis/jailbreak/medical/out-of-scope.
    # Those paths skip the supervisor entirely and jump straight to END.
    return END if state.get("route") == "FINAL" else "session_state"


def _supervisor_node(state: AgentState) -> AgentState:
    """Route the request to the correct specialist agent.

    Reads booking/therapist session state that was pre-loaded by _session_state_node.
    Does not need per-request context directly.
    """
    booking_session = state.get("booking_session") or {}
    therapist_session = state.get("therapist_session") or {}
    has_pending_booking = bool(booking_session.get("pending") or booking_session.get("expired"))
    has_pending_therapist_location = bool(therapist_session.get("pending_query"))
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


def build_booking_subgraph(tools: list[BaseTool]):
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
        booking_session = state.get("booking_session") or {}
        pending_state = booking_session.get("status", "NO_PENDING")
        prompt = (
            f"{BOOKING_EMAIL_MASTER_PROMPT}\n"
            "You are the booking specialist inside a larger LangGraph multi-agent system.\n"
            f"Booking session state at graph entry: {pending_state}. Do not assume anything else from memory; rely on the load_pending_booking tool result.\n\n"
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
        booking_session = state.get("booking_session") or {}
        send_result = _latest_tool_result(state, "send_pending_booking_email")
        if isinstance(send_result, dict):
            if send_result.get("ok") is True:
                return {
                    "active_node": "booking_agent",
                    "response_json": ChatResponse(
                        coach_message="Email sent successfully. I have cleared the pending booking request.",
                        requires_confirmation=False,
                    ).model_dump(),
                }
            error = str(send_result.get("error") or "")
            if "expired" in error.lower():
                return {
                    "active_node": "booking_agent",
                    "response_json": ChatResponse(
                        coach_message=(
                            f"Your pending booking request expired after {BOOKING_TTL_MINUTES} minutes. "
                            "Please start again with therapist email and time."
                        ),
                        requires_confirmation=False,
                    ).model_dump(),
                }

        cancel_result = _latest_tool_result(state, "cancel_pending_booking")
        if isinstance(cancel_result, dict) and cancel_result.get("ok") is True:
            return {
                "active_node": "booking_agent",
                "response_json": ChatResponse(
                    coach_message="Okay, I cancelled the pending booking email request.",
                    requires_confirmation=False,
                ).model_dump(),
            }

        prepare_result = _latest_tool_result(state, "prepare_booking_from_message")
        if isinstance(prepare_result, dict) and prepare_result.get("ok") is True:
            payload = prepare_result.get("payload") or {}
            if isinstance(payload, dict) and _pending_payload_complete(payload):
                proposal = _booking_proposal_from_payload(payload, _expires_at_from_result(prepare_result))
                return {
                    "active_node": "booking_agent",
                    "response_json": ChatResponse(
                        coach_message=(
                            f"I prepared an appointment email to {proposal.therapist_email} for {proposal.requested_time}. "
                            "Reply YES to send or NO to cancel."
                        ),
                        booking_proposal=proposal,
                        requires_confirmation=True,
                    ).model_dump(),
                }
            if isinstance(payload, dict):
                return {
                    "active_node": "booking_agent",
                    "response_json": ChatResponse(
                        coach_message=_missing_booking_fields_message(payload, clarification=payload.get("clarification")),
                        requires_confirmation=False,
                    ).model_dump(),
                }

        load_result = _latest_tool_result(state, "load_pending_booking")
        if isinstance(load_result, dict):
            status = load_result.get("status")
            payload = load_result.get("payload") if isinstance(load_result.get("payload"), dict) else None
            if status == "EXPIRED" or booking_session.get("status") == "EXPIRED":
                return {
                    "active_node": "booking_agent",
                    "response_json": ChatResponse(
                        coach_message=(
                            f"Your pending booking request expired after {BOOKING_TTL_MINUTES} minutes. "
                            "Please start again with therapist email and time."
                        ),
                        requires_confirmation=False,
                    ).model_dump(),
                }
            if status == "PENDING_READY" and payload and _pending_payload_complete(payload):
                proposal = _booking_proposal_from_payload(payload, _expires_at_from_result(load_result))
                return {
                    "active_node": "booking_agent",
                    "response_json": ChatResponse(
                        coach_message=(
                            f"Please confirm sending this request to {proposal.therapist_email} for "
                            f"{proposal.requested_time}. Reply YES to send or NO to cancel."
                        ),
                        booking_proposal=proposal,
                        requires_confirmation=True,
                    ).model_dump(),
                }
            if status == "NO_PENDING":
                # booking_node is responsible for calling prepare_booking_from_message
                # when the user provides email/datetime.  If we reach here it means
                # the LLM asked a clarifying question without calling any tool — that
                # conversation is already in state["messages"], so just guide the user.
                return {
                    "active_node": "booking_agent",
                    "response_json": ChatResponse(
                        coach_message=(
                            "No pending booking found. To book an appointment, "
                            "please share the therapist's email address and your preferred date/time."
                        ),
                        requires_confirmation=False,
                    ).model_dump(),
                }

        return {
            "active_node": "booking_agent",
            "response_json": ChatResponse(
                coach_message="I need a few more details. Could you provide the therapist's email and preferred date/time for the appointment?",
                requires_confirmation=False,
            ).model_dump(),
        }

    g: StateGraph = StateGraph(BookingAgentState)
    g.add_node("booking", booking_node)
    g.add_node("tools", ToolNode(tools))
    g.add_node("format_response", format_response_node)
    g.add_edge(START, "booking")
    g.add_conditional_edges("booking", _booking_route)
    g.add_edge("tools", "booking")
    g.add_edge("format_response", END)
    return g.compile()


def build_therapist_subgraph():
    """Return a compiled LangGraph subgraph for therapist search.

    Flow:
      START → guard ──(_search_params absent: short-circuit)──> END
                    ──(_search_params.location present)────────> search → END

    * ``guard_node``  – deterministic auth/premium check + location extraction.
                        Short-circuits to END by NOT setting ``_search_params``
                        when auth fails or no location is available.
                        Sets ``_search_params`` with pre-extracted params only when
                        a valid location was found so ``search_node`` can proceed.
    * ``search_node`` – calls TherapistSearchHandler.search_with_retries with
                        the pre-extracted parameters and builds response_json.

    ``_search_params`` is absent from parent ``AgentState``, so it is always
    None at the start of each subgraph invocation (never carried over from a
    previous turn) and is silently discarded when merged back to the parent.
    """

    def guard_node(state: TherapistAgentState) -> TherapistAgentState:
        context = _get_ctx()
        therapist_session = state.get("therapist_session") or {}
        messages = state.get("messages") or []
        message = ""
        for m in reversed(messages):
            if isinstance(m, HumanMessage):
                message = str(m.content)
                break

        # No HTTP request context (e.g. unit tests or CLI calls without a request).
        if not context.request:
            return {
                "active_node": "therapist",
                "therapist_session": therapist_session,
                "therapist_search": TherapistSearch(status="unavailable", results=[], message=None),
                "response_json": ChatResponse(
                    coach_message="Therapist search is unavailable right now.",
                    therapists=[],
                ).model_dump(),
            }

        # Authentication check.
        if not context.user and not settings.dev_mode:
            return {
                "active_node": "therapist",
                "therapist_session": therapist_session,
                "therapist_search": TherapistSearch(status="auth_required", results=[], message="Please sign in to use therapist search."),
                "response_json": ChatResponse(
                    coach_message="Please sign in to use therapist search.",
                    premium_cta={"enabled": True, "message": "Sign in and upgrade to premium to unlock therapist search."},
                ).model_dump(),
            }

        # Premium check.
        if context.user and not context.user.is_premium and not settings.dev_mode:
            return {
                "active_node": "therapist",
                "therapist_session": therapist_session,
                "therapist_search": TherapistSearch(status="premium_required", results=[], message="Therapist search is available with premium access."),
                "response_json": ChatResponse(
                    coach_message="Therapist search is available with premium access.",
                    premium_cta={"enabled": True, "message": "Unlock therapist search to see local providers."},
                ).model_dump(),
            }

        # Location extraction — prefer explicit location in message, fall back to
        # a short-reply resolution against a pending multi-turn query.
        therapist_handler = TherapistSearchHandler(
            search_fn=context.therapist_search_fn or mcp_therapist_search,
            dev_mode=settings.dev_mode,
            session_cookie_name=settings.session_cookie_name,
        )
        parsed = therapist_handler.parse_message(message)
        pending_query_dict = therapist_session.get("pending_query") or None
        location = parsed.location_text

        if not location and pending_query_dict and therapist_handler._looks_like_location_reply(message):
            location = extract_location_from_short_reply(message)
            pending_query = TherapistSearchParams(
                location_text=pending_query_dict.get("location_text"),
                radius_km=int(pending_query_dict.get("radius_km") or 25),
                specialty=normalize_specialty(pending_query_dict.get("specialty")),
                limit=int(pending_query_dict.get("limit") or 10),
            )
            parsed = TherapistSearchParams(
                location_text=location,
                radius_km=extract_radius_km(message) or pending_query.radius_km,
                specialty=normalize_specialty(extract_specialty(message)) or pending_query.specialty,
                limit=extract_limit(message) if any(ch.isdigit() for ch in message) else pending_query.limit,
            )

        if not location:
            # No location — ask and store pending_query for multi-turn resolution.
            return {
                "active_node": "therapist",
                "therapist_session": {
                    "remembered_location": None,
                    "pending_query": {
                        "location_text": parsed.location_text,
                        "radius_km": parsed.radius_km,
                        "specialty": parsed.specialty,
                        "limit": parsed.limit,
                    },
                },
                "therapist_search": TherapistSearch(
                    status="needs_location",
                    results=[],
                    message="Please share a city or postcode so I can search nearby providers.",
                ),
                "response_json": ChatResponse(
                    coach_message="Please share a city or postcode so I can search nearby providers.",
                    therapists=[],
                ).model_dump(),
                # _search_params intentionally NOT set → _guard_route routes to END
            }

        # Has a valid location — hand off pre-extracted params to search_node.
        # _search_params is absent from AgentState, so it starts fresh on every
        # invocation and its presence here is the routing signal for _guard_route.
        return {
            "_search_params": {
                "location": location,
                "radius_km": parsed.radius_km,
                "specialty": parsed.specialty,
                "limit": parsed.limit,
            },
        }

    def _guard_route(state: TherapistAgentState) -> str:
        """Route to search if guard extracted a valid location, else short-circuit."""
        params = state.get("_search_params") or {}
        return "search" if params.get("location") else END

    def search_node(state: TherapistAgentState) -> TherapistAgentState:
        context = _get_ctx()
        params = state.get("_search_params") or {}
        location: str = params.get("location", "")
        radius_km: int = params.get("radius_km", 25)
        specialty: str | None = params.get("specialty")
        limit: int = params.get("limit", 10)
        therapist_session = state.get("therapist_session") or {}

        therapist_handler = TherapistSearchHandler(
            search_fn=context.therapist_search_fn or mcp_therapist_search,
            dev_mode=settings.dev_mode,
            session_cookie_name=settings.session_cookie_name,
        )

        try:
            found_results, fallback_reason = therapist_handler.search_with_retries(
                location_text=location,
                radius_km=radius_km,
                specialty=specialty,
                limit=limit,
            )
        except HTTPException:
            found_results, fallback_reason = [], None

        if not found_results:
            final_radius = max(radius_km, 25) if radius_km < 25 else radius_km
            response = ChatResponse(
                coach_message=(
                    f"No providers found near {location} within {final_radius} km. "
                    "Try a different city or a larger radius — I'm here to help."
                ),
                therapists=[],
            )
            next_therapist_session: TherapistSession = {
                "remembered_location": therapist_session.get("remembered_location"),
                "pending_query": None,
            }
        elif fallback_reason == "specialty":
            response = ChatResponse(
                coach_message="No exact specialty match; showing nearby providers.",
                therapists=found_results,
            )
            next_therapist_session = {"remembered_location": location, "pending_query": None}
        elif fallback_reason == "radius":
            response = ChatResponse(
                coach_message="No providers found in the requested radius; showing nearby providers.",
                therapists=found_results,
            )
            next_therapist_session = {"remembered_location": location, "pending_query": None}
        else:
            response = ChatResponse(
                coach_message=f"Here are therapist options near {location}.",
                therapists=found_results,
            )
            next_therapist_session = {"remembered_location": location, "pending_query": None}

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
        else:
            status = "no_results"

        return {
            "active_node": "therapist",
            "therapist_session": next_therapist_session,
            "therapist_search": TherapistSearch(status=status, results=results, message=response.coach_message),
            "response_json": response.model_dump(),
        }

    g: StateGraph = StateGraph(TherapistAgentState)
    g.add_node("guard", guard_node)
    g.add_node("search", search_node)
    g.add_edge(START, "guard")
    g.add_conditional_edges("guard", _guard_route)
    g.add_edge("search", END)
    return g.compile()


def _finalize_node(state: AgentState) -> AgentState:
    """Format the coach subgraph's raw AI messages into a structured ChatResponse.

    Only the coach path reaches this node — safety, therapist, and booking all
    set response_json directly and route to END without going through finalize.
    """
    prompt = (
        "You are the final response formatter for a LangGraph mental health coaching application.\n"
        "The coach agent has just responded. Return only a ChatResponse object.\n"
        "Use the full conversation history and any tool outputs in the messages.\n"
        "Populate coach_message with the coach's response.\n"
        "If the coach retrieved context via tools, incorporate it naturally.\n"
        "Do not invent fields; only populate what the conversation supports.\n"
        "Set risk_level to 'normal' unless the conversation indicates otherwise."
    )
    payload = _structured_chat_response(prompt, state)
    return {"response_json": payload}


# ---------------------------------------------------------------------------
# Singleton graph — compiled exactly once, shared across all requests.
# Per-request context is injected via _REQUEST_CONTEXT (ContextVar) in arun_agent.
# ---------------------------------------------------------------------------

# Build tools once at import time.  Each tool impl calls _get_ctx() at runtime.
_COACH_TOOLS, _BOOKING_TOOLS = _build_tools()

_COMPILED_GRAPH: "Any | None" = None  # CompiledStateGraph; typed as Any to avoid forward-ref issues


def build_graph() -> "Any":
    """Return the singleton compiled LangGraph graph, compiling it on first call."""
    global _COMPILED_GRAPH
    if _COMPILED_GRAPH is None:
        graph = StateGraph(AgentState)
        # trim_history runs FIRST so the checkpointed messages list stays
        # bounded regardless of which downstream path the turn takes.
        graph.add_node("trim_history",   _trim_history_node)
        graph.add_node("safety",         _safety_node)
        graph.add_node("session_state",  _session_state_node)
        graph.add_node("supervisor",     _supervisor_node)
        # True subgraphs — each has its own compiled StateGraph with START/END cycle
        graph.add_node("sentiment_agent", build_sentiment_subgraph())
        graph.add_node("coach_agent",     build_coach_subgraph(_COACH_TOOLS))
        graph.add_node("booking_agent",   build_booking_subgraph(_BOOKING_TOOLS))
        # Therapist subgraph: guard (auth + location) → search (Python handler) → END
        graph.add_node("therapist",       build_therapist_subgraph())
        # finalize is coach-only: structures raw AI messages into ChatResponse
        graph.add_node("finalize",       _finalize_node)
        graph.add_edge(START, "trim_history")
        graph.add_edge("trim_history", "safety")
        graph.add_conditional_edges("safety", _route_after_safety)
        graph.add_edge("session_state", "supervisor")
        graph.add_conditional_edges("supervisor", _route_after_supervisor)
        # Coach path: sentiment → coach → finalize → END
        graph.add_edge("sentiment_agent", "coach_agent")
        graph.add_edge("coach_agent",     "finalize")
        graph.add_edge("finalize",        END)
        # Therapist and booking set response_json themselves — straight to END
        graph.add_edge("therapist",    END)
        graph.add_edge("booking_agent", END)
        _COMPILED_GRAPH = graph.compile(checkpointer=_GRAPH_CHECKPOINTER)
    return _COMPILED_GRAPH


def load_conversation_history(session_id: str) -> list[dict[str, str]]:
    graph = build_graph()
    snapshot = graph.get_state({"configurable": {"thread_id": session_id}})
    if snapshot is None:
        return []
    values = getattr(snapshot, "values", {}) or {}
    messages = values.get("messages") or []
    history: list[dict[str, str]] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            history.append({"role": "user", "content": str(message.content)})
        elif isinstance(message, AIMessage):
            history.append({"role": "assistant", "content": str(message.content)})
    return history


async def arun_agent(
    message: str,
    history: list[dict[str, str]] | None = None,
    session_id: str | None = None,
    context: GraphRuntimeContext | None = None,
) -> dict[str, Any]:
    # Set per-request context in the ContextVar so that node functions and tools
    # can access it without the graph being rebuilt on every call.
    token = _REQUEST_CONTEXT.set(context or GraphRuntimeContext())
    try:
        graph = build_graph()
        thread_id = session_id or str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        input_state = {"messages": [HumanMessage(content=message)]} if session_id else {"messages": _history_to_messages(history, message)}
        state = await graph.ainvoke(input_state, config=config)
    finally:
        _REQUEST_CONTEXT.reset(token)
    return state.get("response_json", {})


def run_agent(
    message: str,
    history: list[dict[str, str]] | None = None,
    session_id: str | None = None,
    context: GraphRuntimeContext | None = None,
) -> dict[str, Any]:
    return asyncio.run(
        arun_agent(
            message=message,
            history=history,
            session_id=session_id,
            context=context,
        )
    )

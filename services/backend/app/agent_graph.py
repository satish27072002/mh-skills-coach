from __future__ import annotations

from typing import Any, Callable, TypedDict

from fastapi import HTTPException
from langgraph.graph import END, StateGraph

from .db import pgvector_ready, retrieve_similar_chunks
from .llm.provider import ProviderError, ProviderNotConfiguredError, generate_chat
from .prompts import COACH_MASTER_PROMPT
from .safety import filter_unsafe_response, is_crisis
from .schemas import ChatResponse, Resource


class AgentState(TypedDict, total=False):
    user_message: str
    risk_level: str
    retrieved_chunks: list[dict[str, Any]]
    response_json: dict[str, Any]


def classify_risk(state: AgentState) -> AgentState:
    message = state.get("user_message", "")
    risk_level = "crisis" if is_crisis(message) else "non_crisis"
    return {"risk_level": risk_level}


def crisis_response(_: AgentState) -> AgentState:
    response = ChatResponse(
        coach_message=(
            "I am really sorry you are feeling this way. If you are in immediate danger, "
            "please call your local emergency number right now. In Sweden, call 112 for emergencies. "
            "If you can, reach out to someone you trust and let them know you need support."
        ),
        resources=[
            Resource(title="Emergency services (Sweden)", url="https://www.112.se/"),
            Resource(
                title="Find local crisis lines",
                url="https://www.iasp.info/resources/Crisis_Centres/"
            )
        ]
    )
    return {"response_json": response.model_dump()}


def retrieve_context(state: AgentState) -> AgentState:
    message = state.get("user_message", "")
    if not pgvector_ready():
        return {"retrieved_chunks": []}
    try:
        chunks = retrieve_similar_chunks(message, top_k=4)
    except ProviderNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"retrieved_chunks": chunks}


def llm_response(state: AgentState) -> AgentState:
    message = state.get("user_message", "")
    chunks = state.get("retrieved_chunks", [])
    context_blocks: list[str] = []
    for idx, chunk in enumerate(chunks, start=1):
        text = (chunk.get("text") or "").strip()
        if not text:
            continue
        metadata = chunk.get("metadata") or {}
        source = metadata.get("source_id") or metadata.get("title") or f"chunk_{idx}"
        context_blocks.append(f"[{idx}] source={source}\n{text}")

    user_prompt = message
    if context_blocks:
        context_text = "\n\n".join(context_blocks)
        user_prompt = (
            "Use the retrieved context only when relevant.\n\n"
            f"Retrieved context:\n{context_text}\n\n"
            f"User message:\n{message}"
        )

    try:
        content = generate_chat(
            messages=[{"role": "user", "content": user_prompt}],
            system_prompt=COACH_MASTER_PROMPT,
            timeout=180.0,
            keep_alive="10m",
            retrieved_chunks_count=len(chunks),
            user_message=message
        )
    except ProviderNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    response = ChatResponse(
        coach_message=content
    )
    response = filter_unsafe_response(response)
    return {"response_json": response.model_dump()}


def format_response(state: AgentState) -> AgentState:
    response = state.get("response_json")
    if response:
        return {"response_json": response}
    return {
        "response_json": ChatResponse(
            coach_message="Thanks for sharing. How can I support you today?"
        ).model_dump()
    }


def _should_route_crisis(state: AgentState) -> str:
    return "crisis_response" if state.get("risk_level") == "crisis" else "retrieve_context"


def build_graph(
    retrieve_fn: Callable[[AgentState], AgentState] | None = None,
    llm_fn: Callable[[AgentState], AgentState] | None = None
):
    graph = StateGraph(AgentState)
    graph.add_node("classify_risk", classify_risk)
    graph.add_node("crisis_response", crisis_response)
    graph.add_node("retrieve_context", retrieve_fn or retrieve_context)
    graph.add_node("llm_response", llm_fn or llm_response)
    graph.add_node("format_response", format_response)

    graph.set_entry_point("classify_risk")
    graph.add_conditional_edges("classify_risk", _should_route_crisis)
    graph.add_edge("crisis_response", "format_response")
    graph.add_edge("retrieve_context", "llm_response")
    graph.add_edge("llm_response", "format_response")
    graph.add_edge("format_response", END)
    return graph.compile()


def run_agent(
    message: str,
    retrieve_fn: Callable[[AgentState], AgentState] | None = None,
    llm_fn: Callable[[AgentState], AgentState] | None = None
) -> dict[str, Any]:
    graph = build_graph(retrieve_fn=retrieve_fn, llm_fn=llm_fn)
    state = graph.invoke({"user_message": message})
    return state.get("response_json", {})

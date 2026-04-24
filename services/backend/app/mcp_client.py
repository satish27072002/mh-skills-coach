from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
from fastapi import HTTPException

from .config import settings
from .schemas import TherapistResult


class MCPClientError(RuntimeError):
    pass


_mcp_client: Any | None = None
_mcp_client_url: str | None = None


def _import_mcp_adapters() -> tuple[type[Any], Any]:
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
        from langchain_mcp_adapters.tools import load_mcp_tools
    except ImportError as exc:
        raise MCPClientError(
            "langchain-mcp-adapters is not installed. Install backend dependencies to use MCP tools."
        ) from exc
    return MultiServerMCPClient, load_mcp_tools


def _mcp_health_url() -> str:
    parsed = urlparse(settings.mcp_base_url)
    path = parsed.path.rstrip("/")
    health_path = path[:-4] + "/health" if path.endswith("/mcp") else "/health"
    return urlunparse(parsed._replace(path=health_path, params="", query="", fragment=""))


def _mcp_health_url_for(base_url: str) -> str:
    parsed = urlparse(base_url)
    path = parsed.path.rstrip("/")
    health_path = path[:-4] + "/health" if path.endswith("/mcp") else "/health"
    return urlunparse(parsed._replace(path=health_path, params="", query="", fragment=""))


def _candidate_mcp_base_urls() -> list[str]:
    configured = settings.mcp_base_url.rstrip("/") + "/"
    parsed = urlparse(configured)
    candidates = [configured]
    if parsed.hostname == "mcp" and parsed.port == 7000:
        localhost_candidate = urlunparse(parsed._replace(netloc="localhost:7001"))
        candidates.append(localhost_candidate.rstrip("/") + "/")
        loopback_candidate = urlunparse(parsed._replace(netloc="127.0.0.1:7001"))
        candidates.append(loopback_candidate.rstrip("/") + "/")
    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def resolve_mcp_base_url() -> str:
    for candidate in _candidate_mcp_base_urls():
        try:
            response = httpx.get(_mcp_health_url_for(candidate), timeout=0.8)
            if response.status_code == 200:
                return candidate
        except httpx.HTTPError:
            continue
    return settings.mcp_base_url.rstrip("/") + "/"


def probe_mcp_health() -> bool:
    if not settings.mcp_base_url:
        return False
    try:
        response = httpx.get(_mcp_health_url_for(resolve_mcp_base_url()), timeout=0.8)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def _get_client() -> Any:
    global _mcp_client, _mcp_client_url
    resolved_base_url = resolve_mcp_base_url()
    if _mcp_client is None or _mcp_client_url != resolved_base_url:
        MultiServerMCPClient, _ = _import_mcp_adapters()
        _mcp_client = MultiServerMCPClient(
            {
                "mh": {
                    "transport": "streamable_http",
                    "url": resolved_base_url,
                }
            }
        )
        _mcp_client_url = resolved_base_url
    return _mcp_client


def _run_async(coro: Any) -> Any:
    return asyncio.run(coro)


async def _get_tools_for_session(session: Any) -> list[Any]:
    _, load_mcp_tools = _import_mcp_adapters()
    return await load_mcp_tools(session)


async def get_mcp_tools() -> list[Any]:
    client = _get_client()
    async with client.session("mh") as session:
        return list(await _get_tools_for_session(session))


async def _get_tool_by_suffix(session: Any, suffix: str) -> Any:
    tools = await _get_tools_for_session(session)
    for tool in tools:
        if tool.name.endswith(suffix):
            return tool
    raise MCPClientError(f"MCP tool not found: {suffix}")


async def ainvoke_mcp_tool(tool_suffix: str, payload: dict[str, Any]) -> Any:
    client = _get_client()
    async with client.session("mh") as session:
        tool = await _get_tool_by_suffix(session, tool_suffix)
        result = await tool.ainvoke(payload)
        return _normalize_mcp_result(result)


def _normalize_mcp_result(result: Any) -> Any:
    structured_content = getattr(result, "structuredContent", None)
    if isinstance(structured_content, (dict, list)):
        return _normalize_mcp_result(structured_content)
    if isinstance(result, dict):
        if "structuredContent" in result and isinstance(result["structuredContent"], (dict, list)):
            return _normalize_mcp_result(result["structuredContent"])
        if result.get("type") == "text" and isinstance(result.get("text"), str):
            return _normalize_mcp_result(result["text"])
        if set(result.keys()) == {"result"}:
            return _normalize_mcp_result(result["result"])
        return result
    if isinstance(result, list):
        normalized_items = [_normalize_mcp_result(item) for item in result]
        if len(normalized_items) == 1 and isinstance(normalized_items[0], (dict, list)):
            return normalized_items[0]
        return normalized_items
    if isinstance(result, str):
        text = result.strip()
        if not text:
            return text
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return result
        return _normalize_mcp_result(parsed)
    return result


async def amcp_therapist_search(
    location_text: str,
    radius_km: int | None = None,
    specialty: str | None = None,
    limit: int = 10,
) -> list[TherapistResult]:
    normalized_specialty = specialty.strip() if isinstance(specialty, str) else None
    if normalized_specialty == "":
        normalized_specialty = None
    payload: dict[str, Any] = {
        "location_text": location_text,
        "radius_km": min(max(radius_km or 25, 1), 50),
        "limit": min(max(limit, 1), 10),
    }
    if normalized_specialty:
        payload["specialty"] = normalized_specialty
    try:
        results = await ainvoke_mcp_tool("therapist_search_tool", payload)
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=502, detail="mcp therapist_search request timed out") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"mcp therapist_search failed: {exc}") from exc
    if isinstance(results, dict):
        results = [results]
    if not isinstance(results, list):
        raise HTTPException(status_code=502, detail="invalid mcp therapist_search payload")

    normalized: list[TherapistResult] = []
    for result in results:
        if not isinstance(result, dict):
            raise HTTPException(status_code=502, detail="invalid mcp therapist_search payload")
        required = {"name", "address", "distance_km", "phone", "email", "source_url"}
        if not required.issubset(result.keys()):
            raise HTTPException(status_code=502, detail="invalid mcp therapist_search payload")
        normalized.append(
            TherapistResult(
                name=result["name"],
                address=result["address"],
                url=result["source_url"] or "https://www.openstreetmap.org",
                phone=result["phone"] or "Phone unavailable",
                distance_km=float(result["distance_km"]) if result["distance_km"] is not None else 0.0,
                email=result["email"],
                source_url=result["source_url"] or "https://www.openstreetmap.org",
            )
        )
    return normalized


def mcp_therapist_search(
    location_text: str,
    radius_km: int | None = None,
    specialty: str | None = None,
    limit: int = 10,
) -> list[TherapistResult]:
    return _run_async(amcp_therapist_search(location_text, radius_km, specialty, limit))


async def amcp_send_email(
    to: str,
    subject: str,
    body: str,
    reply_to: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"to": to, "subject": subject, "body": body}
    if reply_to:
        payload["reply_to"] = reply_to
    try:
        result = await ainvoke_mcp_tool("send_email_tool", payload)
    except httpx.TimeoutException as exc:
        raise MCPClientError("mcp send_email request timed out") from exc
    except Exception as exc:
        raise MCPClientError(f"mcp send_email failed: {exc}") from exc
    if not isinstance(result, dict) or "message_id" not in result:
        raise MCPClientError("invalid mcp send_email payload")
    return {"ok": True, **result}


def mcp_send_email(
    to: str,
    subject: str,
    body: str,
    reply_to: str | None = None,
) -> dict[str, Any]:
    return _run_async(amcp_send_email(to=to, subject=subject, body=body, reply_to=reply_to))

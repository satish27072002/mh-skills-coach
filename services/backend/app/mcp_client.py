from typing import Any

import httpx
from fastapi import HTTPException
from jsonschema import ValidationError, validate

from .config import settings
from .schemas import TherapistResult


class MCPClientError(RuntimeError):
    pass


THERAPIST_SEARCH_SUCCESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ok": {"const": True},
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "address": {"type": "string"},
                    "distance_km": {"type": ["number", "null"]},
                    "phone": {"type": ["string", "null"]},
                    "email": {"type": ["string", "null"]},
                    "source_url": {"type": ["string", "null"]}
                },
                "required": ["name", "address", "distance_km", "phone", "email", "source_url"],
                "additionalProperties": False
            }
        }
    },
    "required": ["ok", "results"],
    "additionalProperties": False
}

TOOL_ERROR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ok": {"const": False},
        "error": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "details": {"type": "object"}
            },
            "required": ["code", "message", "details"],
            "additionalProperties": False
        }
    },
    "required": ["ok", "error"],
    "additionalProperties": False
}

SEND_EMAIL_SUCCESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ok": {"const": True},
        "message_id": {"type": ["string", "null"]}
    },
    "required": ["ok", "message_id"],
    "additionalProperties": False
}


def probe_mcp_health() -> bool:
    if not settings.mcp_base_url:
        return False
    try:
        response = httpx.get(f"{settings.mcp_base_url}/health", timeout=0.8)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def mcp_therapist_search(
    location_text: str,
    radius_km: int | None = None,
    specialty: str | None = None,
    limit: int = 10
) -> list[TherapistResult]:
    normalized_specialty = specialty.strip() if isinstance(specialty, str) else None
    if normalized_specialty == "":
        normalized_specialty = None
    normalized_radius = min(max(radius_km or 25, 1), 50)
    normalized_limit = min(max(limit, 1), 10)
    payload: dict[str, Any] = {
        "location_text": location_text,
        "radius_km": normalized_radius,
        "limit": normalized_limit
    }
    if normalized_specialty:
        payload["specialty"] = normalized_specialty

    try:
        response = httpx.post(
            f"{settings.mcp_base_url}/tools/therapist_search",
            json=payload,
            timeout=8.0
        )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=502, detail="mcp therapist_search request timed out") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="mcp therapist_search request failed") from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="invalid mcp response body") from exc

    if response.status_code >= 400:
        try:
            validate(instance=body, schema=TOOL_ERROR_SCHEMA)
            code = body["error"]["code"]
            message = body["error"]["message"]
            raise HTTPException(
                status_code=502,
                detail=f"mcp therapist_search error ({code}): {message}"
            )
        except ValidationError:
            raise HTTPException(status_code=502, detail="mcp therapist_search returned invalid error payload")

    try:
        validate(instance=body, schema=THERAPIST_SEARCH_SUCCESS_SCHEMA)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail="invalid mcp therapist_search payload") from exc

    normalized: list[TherapistResult] = []
    for result in body["results"]:
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


def mcp_send_email(
    to: str,
    subject: str,
    body: str,
    reply_to: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "to": to,
        "subject": subject,
        "body": body
    }
    if reply_to:
        payload["reply_to"] = reply_to

    try:
        response = httpx.post(
            f"{settings.mcp_base_url}/tools/send_email",
            json=payload,
            timeout=8.0
        )
    except httpx.TimeoutException as exc:
        raise MCPClientError("mcp send_email request timed out") from exc
    except httpx.HTTPError as exc:
        raise MCPClientError("mcp send_email request failed") from exc

    try:
        body_json = response.json()
    except ValueError as exc:
        raise MCPClientError("invalid mcp send_email response body") from exc

    if response.status_code >= 400:
        try:
            validate(instance=body_json, schema=TOOL_ERROR_SCHEMA)
        except ValidationError as exc:
            raise MCPClientError("mcp send_email returned invalid error payload") from exc
        error = body_json["error"]
        raise MCPClientError(f"mcp send_email error ({error['code']}): {error['message']}")

    try:
        validate(instance=body_json, schema=SEND_EMAIL_SUCCESS_SCHEMA)
    except ValidationError as exc:
        raise MCPClientError("invalid mcp send_email payload") from exc
    return body_json

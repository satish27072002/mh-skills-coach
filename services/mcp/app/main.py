from __future__ import annotations

import os
import smtplib
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from jsonschema import FormatChecker, ValidationError, validate

from .send_email import send_email_via_smtp
from .therapist_search import therapist_search


app = FastAPI(title="mh-skills-mcp")


THERAPIST_SEARCH_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "location_text": {"type": "string", "minLength": 1},
        "radius_km": {"type": "number", "minimum": 1, "maximum": 50},
        "specialty": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 20}
    },
    "required": ["location_text"],
    "additionalProperties": False
}

THERAPIST_SEARCH_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean", "const": True},
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

ERROR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean", "const": False},
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

SEND_EMAIL_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "to": {"type": "string", "format": "email"},
        "subject": {"type": "string", "minLength": 1, "maxLength": 160},
        "body": {"type": "string", "minLength": 1, "maxLength": 10000},
        "reply_to": {"type": "string", "format": "email"}
    },
    "required": ["to", "subject", "body"],
    "additionalProperties": False
}

SEND_EMAIL_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean", "const": True},
        "message_id": {"type": ["string", "null"]}
    },
    "required": ["ok", "message_id"],
    "additionalProperties": False
}

FORMAT_CHECKER = FormatChecker()


def _tool_error(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    status_code: int = 400
) -> JSONResponse:
    payload = {"ok": False, "error": {"code": code, "message": message, "details": details or {}}}
    validate(instance=payload, schema=ERROR_SCHEMA)
    return JSONResponse(status_code=status_code, content=payload)


def _extract_tool_payload(raw_body: Any, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(raw_body, dict):
        raise ValueError("Body must be a JSON object.")
    candidate = raw_body.get("params") if "params" in raw_body else raw_body
    if not isinstance(candidate, dict):
        raise ValueError("Tool payload must be an object.")
    payload = dict(candidate)
    for key, value in (defaults or {}).items():
        payload.setdefault(key, value)
    return payload


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tools/therapist_search")
async def tool_therapist_search(request: Request):
    try:
        body = await request.json()
        payload = _extract_tool_payload(body, defaults={"radius_km": 5, "limit": 5})
        validate(instance=payload, schema=THERAPIST_SEARCH_INPUT_SCHEMA, format_checker=FORMAT_CHECKER)
    except ValidationError as exc:
        return _tool_error(
            "INVALID_ARGUMENT",
            "Invalid therapist_search input.",
            details={"validation_error": exc.message},
            status_code=400
        )
    except ValueError as exc:
        return _tool_error(
            "INVALID_ARGUMENT",
            str(exc),
            status_code=400
        )
    except Exception:
        return _tool_error(
            "INVALID_ARGUMENT",
            "Malformed JSON payload.",
            status_code=400
        )

    try:
        results = therapist_search(
            location_text=str(payload["location_text"]),
            radius_km=float(payload["radius_km"]),
            specialty=str(payload["specialty"]) if payload.get("specialty") else None,
            limit=int(payload["limit"]),
            nominatim_base_url=os.getenv("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org"),
            overpass_base_url=os.getenv("OVERPASS_BASE_URL", "https://overpass-api.de"),
            user_agent=os.getenv("THERAPIST_SEARCH_USER_AGENT", "mh-skills-coach-mcp/0.1")
        )
    except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError) as exc:
        return _tool_error(
            "UPSTREAM_ERROR",
            "Therapist search upstream request failed.",
            details={"error_type": type(exc).__name__},
            status_code=502
        )
    except Exception as exc:
        return _tool_error(
            "INTERNAL",
            "Therapist search failed unexpectedly.",
            details={"error_type": type(exc).__name__},
            status_code=500
        )

    success_payload = {"ok": True, "results": results}
    try:
        validate(instance=success_payload, schema=THERAPIST_SEARCH_OUTPUT_SCHEMA, format_checker=FORMAT_CHECKER)
    except ValidationError as exc:
        return _tool_error(
            "INTERNAL",
            "Tool produced an invalid response.",
            details={"validation_error": exc.message},
            status_code=500
        )
    return JSONResponse(status_code=200, content=success_payload)


@app.post("/tools/send_email")
async def tool_send_email(request: Request):
    try:
        body = await request.json()
        payload = _extract_tool_payload(body)
        validate(instance=payload, schema=SEND_EMAIL_INPUT_SCHEMA, format_checker=FORMAT_CHECKER)
    except ValidationError as exc:
        return _tool_error(
            "INVALID_ARGUMENT",
            "Invalid send_email input.",
            details={"validation_error": exc.message},
            status_code=400
        )
    except ValueError as exc:
        return _tool_error(
            "INVALID_ARGUMENT",
            str(exc),
            status_code=400
        )
    except Exception:
        return _tool_error(
            "INVALID_ARGUMENT",
            "Malformed JSON payload.",
            status_code=400
        )

    try:
        message_id = send_email_via_smtp(
            to=str(payload["to"]),
            subject=str(payload["subject"]),
            body=str(payload["body"]),
            reply_to=str(payload["reply_to"]) if payload.get("reply_to") else None
        )
    except ValueError as exc:
        return _tool_error(
            "INTERNAL",
            str(exc),
            details={},
            status_code=500
        )
    except (smtplib.SMTPException, OSError) as exc:
        return _tool_error(
            "SMTP_ERROR",
            "Failed to deliver email via SMTP.",
            details={"error_type": type(exc).__name__},
            status_code=502
        )
    except Exception as exc:
        return _tool_error(
            "INTERNAL",
            "Unexpected send_email failure.",
            details={"error_type": type(exc).__name__},
            status_code=500
        )

    success_payload = {"ok": True, "message_id": message_id}
    try:
        validate(instance=success_payload, schema=SEND_EMAIL_OUTPUT_SCHEMA, format_checker=FORMAT_CHECKER)
    except ValidationError as exc:
        return _tool_error(
            "INTERNAL",
            "Tool produced an invalid response.",
            details={"validation_error": exc.message},
            status_code=500
        )
    return JSONResponse(status_code=200, content=success_payload)

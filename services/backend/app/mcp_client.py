from typing import Any

import httpx
from fastapi import HTTPException
from jsonschema import ValidationError, validate

from .config import settings
from .schemas import Resource

BOOKING_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "providers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "description": {"type": "string"}
                },
                "required": ["title", "url", "description"]
            }
        }
    },
    "required": ["providers"]
}


def suggest_providers(params: dict[str, Any] | None = None) -> list[Resource]:
    url = f"{settings.mcp_base_url}/tools/booking.suggest_providers"
    try:
        response = httpx.post(url, json={"params": params or {}}, timeout=5.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="mcp request failed") from exc

    payload = response.json()
    result = payload.get("result")
    try:
        validate(instance=result, schema=BOOKING_RESULT_SCHEMA)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail="invalid mcp response") from exc

    return [
        Resource(
            title=provider["title"],
            url=provider["url"],
            description=provider["description"]
        )
        for provider in result["providers"]
    ]

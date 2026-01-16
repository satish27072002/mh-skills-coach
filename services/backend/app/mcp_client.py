from typing import Any

import httpx
from fastapi import HTTPException
from jsonschema import ValidationError, validate

from .config import settings
from .schemas import Resource, TherapistResult

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

THERAPIST_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "therapists": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "address": {"type": "string"},
                    "url": {"type": "string"},
                    "phone": {"type": "string"},
                    "distance_km": {"type": "number"}
                },
                "required": ["name", "address", "url", "phone", "distance_km"]
            }
        }
    },
    "required": ["therapists"]
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


def search_therapists(location: str, radius_km: int | None = None) -> list[TherapistResult]:
    url = f"{settings.mcp_base_url}/tools/booking.search_therapists"
    params = {"location": location}
    if radius_km is not None:
        params["radius_km"] = radius_km
    try:
        response = httpx.post(url, json={"params": params}, timeout=5.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="mcp request failed") from exc

    payload = response.json()
    result = payload.get("result")
    try:
        validate(instance=result, schema=THERAPIST_SEARCH_SCHEMA)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail="invalid mcp response") from exc

    return [
        TherapistResult(
            name=therapist["name"],
            address=therapist["address"],
            url=therapist["url"],
            phone=therapist["phone"],
            distance_km=therapist["distance_km"]
        )
        for therapist in result["therapists"]
    ]

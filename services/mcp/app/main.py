from typing import Any

from fastapi import FastAPI, HTTPException
from jsonschema import ValidationError, validate
from pydantic import BaseModel

app = FastAPI(title="mh-skills-mcp")


class ToolRequest(BaseModel):
    params: dict[str, Any] | None = None


KNOWLEDGE_CARDS = [
    {
        "chunk_id": "grounding-54321",
        "title": "5-4-3-2-1 grounding",
        "snippet": "Notice 5 things you can see, 4 you can feel, 3 you can hear..."
    },
    {
        "chunk_id": "box-breathing",
        "title": "Box breathing",
        "snippet": "Inhale 4, hold 4, exhale 4, hold 4. Repeat slowly."
    }
]

PROVIDERS = [
    {
        "name": "Mindler",
        "url": "https://www.mindler.se/",
        "region": "Sweden",
        "languages": ["sv", "en"],
        "format": ["online"]
    },
    {
        "name": "Kry",
        "url": "https://www.kry.se/",
        "region": "Sweden",
        "languages": ["sv", "en"],
        "format": ["online", "in_person"]
    },
    {
        "name": "Psychology Today",
        "url": "https://www.psychologytoday.com/",
        "region": "Global",
        "languages": ["en"],
        "format": ["online", "in_person"]
    }
]

TOOL_RESPONSE_SCHEMAS = {
    "kb.search": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "chunk_id": {"type": "string"},
                        "title": {"type": "string"},
                        "snippet": {"type": "string"}
                    },
                    "required": ["chunk_id", "title", "snippet"]
                }
            }
        },
        "required": ["items"]
    },
    "kb.get_chunk": {
        "type": "object",
        "properties": {
            "chunk": {
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string"}
                },
                "required": ["chunk_id", "title", "content"]
            }
        },
        "required": ["chunk"]
    },
    "premium.check_entitlement": {
        "type": "object",
        "properties": {"is_premium": {"type": "boolean"}},
        "required": ["is_premium"]
    },
    "booking.suggest_providers": {
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
    },
    "booking.search_therapists": {
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
    },
    "payments.create_checkout_session": {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"]
    },
    "audit.log": {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"]
    }
}


def _validate(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    schema = TOOL_RESPONSE_SCHEMAS.get(tool_name)
    if not schema:
        raise HTTPException(status_code=404, detail="unknown tool")
    try:
        validate(instance=payload, schema=schema)
    except ValidationError as exc:
        raise HTTPException(status_code=500, detail="invalid tool response") from exc
    return payload


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tools/kb.search")
def kb_search(request: ToolRequest) -> dict[str, Any]:
    query = (request.params or {}).get("query", "").lower()
    results = [card for card in KNOWLEDGE_CARDS if query in card["title"].lower()]
    if not results:
        results = KNOWLEDGE_CARDS
    payload = {"items": results}
    return {"result": _validate("kb.search", payload)}


@app.post("/tools/kb.get_chunk")
def kb_get_chunk(request: ToolRequest) -> dict[str, Any]:
    chunk_id = (request.params or {}).get("chunk_id")
    match = next((card for card in KNOWLEDGE_CARDS if card["chunk_id"] == chunk_id), None)
    if not match:
        match = KNOWLEDGE_CARDS[0]
    payload = {
        "chunk": {
            "chunk_id": match["chunk_id"],
            "title": match["title"],
            "content": match["snippet"]
        }
    }
    return {"result": _validate("kb.get_chunk", payload)}


@app.post("/tools/premium.check_entitlement")
def premium_check(_: ToolRequest) -> dict[str, Any]:
    payload = {"is_premium": False}
    return {"result": _validate("premium.check_entitlement", payload)}


@app.post("/tools/booking.suggest_providers")
def booking_suggest(request: ToolRequest) -> dict[str, Any]:
    filters = request.params or {}
    region = filters.get("region")
    language = filters.get("language")
    format_pref = filters.get("format")

    filtered = PROVIDERS
    if region:
        filtered = [provider for provider in filtered if provider["region"].lower() == region.lower()]
    if language:
        filtered = [provider for provider in filtered if language in provider["languages"]]
    if format_pref:
        filtered = [provider for provider in filtered if format_pref in provider["format"]]

    payload = {
        "providers": [
            {
                "title": provider["name"],
                "url": provider["url"],
                "description": "Curated licensed platform with transparent intake."
            }
            for provider in filtered
        ]
    }
    return {"result": _validate("booking.suggest_providers", payload)}


def _mock_therapists(location: str) -> list[dict[str, Any]]:
    normalized = location.strip() or "your area"
    base_distance = max(1.0, min(12.0, len(normalized) * 0.3))
    return [
        {
            "name": f"{normalized} Counseling Center",
            "address": f"12 Main St, {normalized}",
            "url": "https://example.com/therapy/center",
            "phone": "+46 8 123 000",
            "distance_km": round(base_distance, 1)
        },
        {
            "name": f"{normalized} Wellbeing Clinic",
            "address": f"45 Oak Ave, {normalized}",
            "url": "https://example.com/therapy/clinic",
            "phone": "+46 8 555 010",
            "distance_km": round(base_distance + 1.8, 1)
        },
        {
            "name": f"{normalized} Talk Therapy Studio",
            "address": f"7 River Rd, {normalized}",
            "url": "https://example.com/therapy/studio",
            "phone": "+46 8 777 011",
            "distance_km": round(base_distance + 3.4, 1)
        }
    ]


@app.post("/tools/booking.search_therapists")
def booking_search(request: ToolRequest) -> dict[str, Any]:
    params = request.params or {}
    location = str(params.get("location", "")).strip()
    payload = {"therapists": _mock_therapists(location)}
    return {"result": _validate("booking.search_therapists", payload)}


@app.post("/tools/payments.create_checkout_session")
def payments_checkout(_: ToolRequest) -> dict[str, Any]:
    payload = {"url": "https://checkout.stripe.com/test/session"}
    return {"result": _validate("payments.create_checkout_session", payload)}


@app.post("/tools/audit.log")
def audit_log(_: ToolRequest) -> dict[str, Any]:
    payload = {"ok": True}
    return {"result": _validate("audit.log", payload)}

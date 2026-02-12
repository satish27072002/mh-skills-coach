from __future__ import annotations

import math
import time
from typing import Any

import httpx


GEOCODE_TIMEOUT = httpx.Timeout(8.0, connect=4.0)
OVERPASS_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
RETRY_DELAYS = [0.4, 0.8]


def _nominatim_endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/search"):
        return base
    return f"{base}/search"


def _overpass_endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/api/interpreter"):
        return base
    return f"{base}/api/interpreter"


def _retry_request_get(url: str, params: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            response = httpx.get(url, params=params, headers=headers, timeout=GEOCODE_TIMEOUT)
            response.raise_for_status()
            return response
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:
            last_error = exc
            if attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
                continue
            raise
    raise RuntimeError("Unexpected geocoding retry failure.") from last_error


def _retry_request_post(url: str, content: str, headers: dict[str, str]) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            response = httpx.post(url, content=content, headers=headers, timeout=OVERPASS_TIMEOUT)
            if response.status_code in {429, 500, 502, 503, 504}:
                raise httpx.HTTPStatusError(
                    "upstream temporary error",
                    request=response.request,
                    response=response
                )
            response.raise_for_status()
            return response
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError, httpx.HTTPStatusError) as exc:
            last_error = exc
            if attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
                continue
            raise
    raise RuntimeError("Unexpected overpass retry failure.") from last_error


def geocode_location(
    location_text: str,
    nominatim_base_url: str,
    user_agent: str
) -> tuple[float, float] | None:
    if not location_text.strip():
        return None
    response = _retry_request_get(
        _nominatim_endpoint(nominatim_base_url),
        params={"q": location_text, "format": "json", "limit": 1},
        headers={"User-Agent": user_agent, "Accept": "application/json"},
    )
    payload = response.json()
    if not isinstance(payload, list) or not payload:
        return None
    try:
        lat = float(payload[0]["lat"])
        lon = float(payload[0]["lon"])
    except (KeyError, ValueError, TypeError):
        return None
    return lat, lon


def _build_overpass_query(lat: float, lon: float, radius_m: int) -> str:
    return f"""
    [out:json][timeout:25];
    (
      node["healthcare"="psychotherapist"](around:{radius_m},{lat},{lon});
      way["healthcare"="psychotherapist"](around:{radius_m},{lat},{lon});
      relation["healthcare"="psychotherapist"](around:{radius_m},{lat},{lon});
      node["healthcare"="psychologist"](around:{radius_m},{lat},{lon});
      way["healthcare"="psychologist"](around:{radius_m},{lat},{lon});
      relation["healthcare"="psychologist"](around:{radius_m},{lat},{lon});
      node["healthcare"="psychiatrist"](around:{radius_m},{lat},{lon});
      way["healthcare"="psychiatrist"](around:{radius_m},{lat},{lon});
      relation["healthcare"="psychiatrist"](around:{radius_m},{lat},{lon});
      node["healthcare"="counselling"](around:{radius_m},{lat},{lon});
      way["healthcare"="counselling"](around:{radius_m},{lat},{lon});
      relation["healthcare"="counselling"](around:{radius_m},{lat},{lon});
      node["amenity"="clinic"]["healthcare:speciality"~"psych|psychiatry|psychotherapy",i](around:{radius_m},{lat},{lon});
      way["amenity"="clinic"]["healthcare:speciality"~"psych|psychiatry|psychotherapy",i](around:{radius_m},{lat},{lon});
      relation["amenity"="clinic"]["healthcare:speciality"~"psych|psychiatry|psychotherapy",i](around:{radius_m},{lat},{lon});
    );
    out center tags;
    """


def overpass_search(
    lat: float,
    lon: float,
    radius_km: float,
    overpass_base_url: str,
    user_agent: str
) -> list[dict[str, Any]]:
    query = _build_overpass_query(lat, lon, int(radius_km * 1000))
    response = _retry_request_post(
        _overpass_endpoint(overpass_base_url),
        content=query,
        headers={"User-Agent": user_agent, "Accept": "application/json"},
    )
    payload = response.json()
    if not isinstance(payload, dict):
        return []
    elements = payload.get("elements")
    return elements if isinstance(elements, list) else []


def _format_address(tags: dict[str, Any]) -> str:
    full = tags.get("addr:full")
    if full:
        return str(full)
    parts: list[str] = []
    street = tags.get("addr:street")
    number = tags.get("addr:housenumber")
    if street:
        parts.append(f"{street} {number}".strip() if number else str(street))
    city = tags.get("addr:city")
    postcode = tags.get("addr:postcode")
    locality = " ".join([part for part in [postcode, city] if part])
    if locality:
        parts.append(locality)
    return ", ".join(parts) if parts else "Address unavailable"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def _matches_specialty(tags: dict[str, Any], specialty: str | None) -> bool:
    if not specialty:
        return True
    joined = " ".join(str(value).lower() for value in tags.values() if value is not None)
    return specialty.lower() in joined


def normalize_results(
    elements: list[dict[str, Any]],
    origin_lat: float,
    origin_lon: float,
    specialty: str | None,
    limit: int
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for element in elements:
        lat = element.get("lat") or element.get("center", {}).get("lat")
        lon = element.get("lon") or element.get("center", {}).get("lon")
        if lat is None or lon is None:
            continue
        tags = element.get("tags") if isinstance(element.get("tags"), dict) else {}
        if not _matches_specialty(tags, specialty):
            continue
        name = str(tags.get("name") or tags.get("brand") or "Therapist")
        address = _format_address(tags)
        phone = tags.get("phone") or tags.get("contact:phone")
        email = tags.get("email") or tags.get("contact:email")
        website = tags.get("website") or tags.get("contact:website")
        osm_type = element.get("type")
        osm_id = element.get("id")
        source_url = website
        if not source_url and osm_type and osm_id:
            source_url = f"https://www.openstreetmap.org/{osm_type}/{osm_id}"
        distance_km = _haversine_km(origin_lat, origin_lon, float(lat), float(lon))
        normalized.append(
            {
                "name": name,
                "address": address,
                "distance_km": round(distance_km, 2),
                "phone": str(phone) if phone else None,
                "email": str(email) if email else None,
                "source_url": str(source_url) if source_url else None
            }
        )
    normalized.sort(
        key=lambda item: item["distance_km"] if item["distance_km"] is not None else 10_000.0
    )
    return normalized[:limit]


def therapist_search(
    *,
    location_text: str,
    radius_km: float,
    specialty: str | None,
    limit: int,
    nominatim_base_url: str,
    overpass_base_url: str,
    user_agent: str,
) -> list[dict[str, Any]]:
    coords = geocode_location(
        location_text=location_text,
        nominatim_base_url=nominatim_base_url,
        user_agent=user_agent
    )
    if not coords:
        return []
    lat, lon = coords
    elements = overpass_search(
        lat=lat,
        lon=lon,
        radius_km=radius_km,
        overpass_base_url=overpass_base_url,
        user_agent=user_agent
    )
    return normalize_results(
        elements=elements,
        origin_lat=lat,
        origin_lon=lon,
        specialty=specialty,
        limit=limit
    )

from __future__ import annotations

import math
import time
from typing import Any

import httpx

from .config import settings
from .schemas import TherapistResult

GEOCODE_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
OVERPASS_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
CACHE_TTL_SECONDS = 60 * 15

_CACHE: dict[tuple[str, int], tuple[float, list[TherapistResult]]] = {}
_REQUEST_TIMES: list[float] = []


def clear_cache() -> None:
    _CACHE.clear()
    _REQUEST_TIMES.clear()


def _allow_request() -> bool:
    now = time.time()
    while _REQUEST_TIMES and now - _REQUEST_TIMES[0] > 60:
        _REQUEST_TIMES.pop(0)
    if len(_REQUEST_TIMES) >= 30:
        return False
    _REQUEST_TIMES.append(now)
    return True


def geocode_location(query: str) -> tuple[float, float] | None:
    if not query.strip():
        return None
    try:
        response = httpx.get(
            f"{settings.nominatim_base_url}/search",
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": settings.therapist_search_user_agent},
            timeout=GEOCODE_TIMEOUT
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.RequestError:
        raise

    if not payload:
        return None
    try:
        lat = float(payload[0]["lat"])
        lon = float(payload[0]["lon"])
    except (KeyError, ValueError, TypeError):
        return None
    return lat, lon


def overpass_search(lat: float, lon: float, radius_m: int) -> list[dict[str, Any]]:
    query = f"""
    [out:json][timeout:25];
    (
      node["healthcare"="psychotherapist"](around:{radius_m},{lat},{lon});
      way["healthcare"="psychotherapist"](around:{radius_m},{lat},{lon});
      relation["healthcare"="psychotherapist"](around:{radius_m},{lat},{lon});
      node["healthcare"="counselling"](around:{radius_m},{lat},{lon});
      way["healthcare"="counselling"](around:{radius_m},{lat},{lon});
      relation["healthcare"="counselling"](around:{radius_m},{lat},{lon});
      node["amenity"="doctors"]["healthcare:speciality"~"psych|psychiatry|psychotherapy",i](around:{radius_m},{lat},{lon});
      way["amenity"="doctors"]["healthcare:speciality"~"psych|psychiatry|psychotherapy",i](around:{radius_m},{lat},{lon});
      relation["amenity"="doctors"]["healthcare:speciality"~"psych|psychiatry|psychotherapy",i](around:{radius_m},{lat},{lon});
    );
    out center tags;
    """
    try:
        response = httpx.post(
            f"{settings.overpass_base_url}/api/interpreter",
            content=query,
            headers={"User-Agent": settings.therapist_search_user_agent},
            timeout=OVERPASS_TIMEOUT
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.RequestError:
        raise

    return payload.get("elements", [])


def _format_address(tags: dict[str, Any]) -> str:
    full = tags.get("addr:full")
    if full:
        return full
    parts: list[str] = []
    street = tags.get("addr:street")
    number = tags.get("addr:housenumber")
    if street:
        parts.append(f"{street} {number}".strip() if number else street)
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


def normalize_providers(
    elements: list[dict[str, Any]],
    origin_lat: float,
    origin_lon: float,
    limit: int
) -> list[TherapistResult]:
    providers: list[TherapistResult] = []
    for element in elements:
        lat = element.get("lat") or element.get("center", {}).get("lat")
        lon = element.get("lon") or element.get("center", {}).get("lon")
        if lat is None or lon is None:
            continue
        tags = element.get("tags") or {}
        name = tags.get("name") or tags.get("brand") or "Therapist"
        address = _format_address(tags)
        phone = tags.get("phone") or tags.get("contact:phone") or ""
        website = tags.get("website") or tags.get("contact:website")
        osm_url = f"https://www.openstreetmap.org/{element.get('type')}/{element.get('id')}"
        url = website or osm_url
        distance_km = _haversine_km(origin_lat, origin_lon, float(lat), float(lon))
        providers.append(
            TherapistResult(
                name=name,
                address=address,
                url=url,
                phone=phone,
                distance_km=round(distance_km, 2)
            )
        )
    providers.sort(key=lambda provider: provider.distance_km)
    return providers[:limit]


def _demo_providers(query: str) -> list[TherapistResult]:
    return [
        TherapistResult(
            name=f"{query.title()} Counseling",
            address=f"{query.title()} Center",
            url="https://www.openstreetmap.org/",
            phone="",
            distance_km=0.5
        )
    ]


def search_therapists(query: str, radius_km: int | None = None) -> list[TherapistResult]:
    normalized_query = query.strip().lower()
    if not settings.therapist_search_enabled:
        return []
    radius = radius_km or settings.therapist_search_radius_km_default
    radius_m = int(radius * 1000)
    cache_key = (normalized_query, radius)
    now = time.time()
    cached = _CACHE.get(cache_key)
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    if not _allow_request():
        return []

    try:
        coords = geocode_location(query)
        if not coords:
            return _demo_providers(query) if settings.demo_mode else []
        lat, lon = coords
        elements = overpass_search(lat, lon, radius_m)
        providers = normalize_providers(elements, lat, lon, limit=settings.therapist_search_limit)
        if not providers and settings.demo_mode:
            providers = _demo_providers(query)
        _CACHE[cache_key] = (now, providers)
        return providers
    except httpx.RequestError:
        return []

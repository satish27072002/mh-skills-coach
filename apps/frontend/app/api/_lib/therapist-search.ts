import Ajv from "ajv";
import type { TherapistResult } from "./safety";

const ajv = new Ajv({ allErrors: true });

const nominatimSchema = {
  type: "array",
  items: {
    type: "object",
    properties: {
      lat: { type: "string" },
      lon: { type: "string" }
    },
    required: ["lat", "lon"],
    additionalProperties: true
  }
} as const;

const overpassSchema = {
  type: "object",
  properties: {
    elements: {
      type: "array",
      items: {
        type: "object",
        properties: {
          type: { type: "string" },
          id: { type: "number" },
          lat: { type: "number" },
          lon: { type: "number" },
          center: {
            type: "object",
            properties: {
              lat: { type: "number" },
              lon: { type: "number" }
            },
            required: ["lat", "lon"],
            additionalProperties: true
          },
          tags: { type: "object" }
        },
        required: ["type", "id"],
        additionalProperties: true
      }
    }
  },
  required: ["elements"],
  additionalProperties: true
} as const;

const validateNominatim = ajv.compile(nominatimSchema);
const validateOverpass = ajv.compile(overpassSchema);

const CACHE_TTL_MS = 10 * 60 * 1000;
const REQUEST_LIMIT = 30;

const cache = new Map<string, { expiresAt: number; results: TherapistResult[] }>();
const requestTimes: number[] = [];

const nominatimBase = (process.env.NOMINATIM_BASE_URL || "https://nominatim.openstreetmap.org").replace(/\/$/, "");
const overpassBase = (process.env.OVERPASS_BASE_URL || "https://overpass-api.de").replace(/\/$/, "");
const parsedRadius = Number(process.env.THERAPIST_SEARCH_RADIUS_KM_DEFAULT || 10);
const parsedLimit = Number(process.env.THERAPIST_SEARCH_LIMIT || 10);
const defaultRadiusKm = Number.isFinite(parsedRadius) ? parsedRadius : 10;
const limit = Number.isFinite(parsedLimit) ? parsedLimit : 10;
const userAgent = process.env.THERAPIST_SEARCH_USER_AGENT || "mh-skills-coach/0.1 (vercel)";

const allowRequest = () => {
  const now = Date.now();
  while (requestTimes.length > 0 && now - requestTimes[0] > 60_000) {
    requestTimes.shift();
  }
  if (requestTimes.length >= REQUEST_LIMIT) {
    return false;
  }
  requestTimes.push(now);
  return true;
};

const fetchWithTimeout = async (url: string, init: RequestInit, timeoutMs: number) => {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
};

const nominatimEndpoint = () => {
  if (nominatimBase.endsWith("/search")) {
    return nominatimBase;
  }
  return `${nominatimBase}/search`;
};

const overpassEndpoint = () => {
  if (overpassBase.endsWith("/api/interpreter")) {
    return overpassBase;
  }
  return `${overpassBase}/api/interpreter`;
};

const geocodeLocation = async (query: string): Promise<[number, number] | null> => {
  if (!query.trim()) {
    return null;
  }
  const url = new URL(nominatimEndpoint());
  url.searchParams.set("q", query);
  url.searchParams.set("format", "json");
  url.searchParams.set("limit", "1");

  const res = await fetchWithTimeout(
    url.toString(),
    {
      headers: {
        "User-Agent": userAgent,
        Accept: "application/json"
      }
    },
    10_000
  );

  if (!res.ok) {
    return null;
  }
  const payload: unknown = await res.json();
  if (!validateNominatim(payload)) {
    return null;
  }
  const results = payload as Array<{ lat: string; lon: string }>;
  if (results.length === 0) {
    return null;
  }
  const lat = Number(results[0]?.lat);
  const lon = Number(results[0]?.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return null;
  }
  return [lat, lon];
};

const overpassSearch = async (lat: number, lon: number, radiusM: number) => {
  const query = `
  [out:json][timeout:25];
  (
    node["healthcare"="psychotherapist"](around:${radiusM},${lat},${lon});
    way["healthcare"="psychotherapist"](around:${radiusM},${lat},${lon});
    relation["healthcare"="psychotherapist"](around:${radiusM},${lat},${lon});
    node["healthcare"="psychologist"](around:${radiusM},${lat},${lon});
    way["healthcare"="psychologist"](around:${radiusM},${lat},${lon});
    relation["healthcare"="psychologist"](around:${radiusM},${lat},${lon});
    node["healthcare"="psychiatrist"](around:${radiusM},${lat},${lon});
    way["healthcare"="psychiatrist"](around:${radiusM},${lat},${lon});
    relation["healthcare"="psychiatrist"](around:${radiusM},${lat},${lon});
    node["healthcare"="counselling"](around:${radiusM},${lat},${lon});
    way["healthcare"="counselling"](around:${radiusM},${lat},${lon});
    relation["healthcare"="counselling"](around:${radiusM},${lat},${lon});
    node["amenity"="clinic"]["healthcare:speciality"~"psych|psychiatry|psychotherapy",i](around:${radiusM},${lat},${lon});
    way["amenity"="clinic"]["healthcare:speciality"~"psych|psychiatry|psychotherapy",i](around:${radiusM},${lat},${lon});
    relation["amenity"="clinic"]["healthcare:speciality"~"psych|psychiatry|psychotherapy",i](around:${radiusM},${lat},${lon});
  );
  out center tags;
  `;

  const res = await fetchWithTimeout(
    overpassEndpoint(),
    {
      method: "POST",
      headers: {
        "User-Agent": userAgent,
        Accept: "application/json"
      },
      body: query
    },
    25_000
  );

  if (res.status === 429 || res.status >= 500) {
    return [];
  }
  if (!res.ok) {
    return [];
  }
  const payload: unknown = await res.json();
  if (!validateOverpass(payload)) {
    return [];
  }
  const data = payload as { elements: Array<Record<string, unknown>> };
  return data.elements;
};

const formatAddress = (tags: Record<string, unknown>) => {
  const full = tags["addr:full"];
  if (typeof full === "string" && full.trim()) {
    return full;
  }
  const parts: string[] = [];
  const street = tags["addr:street"];
  const number = tags["addr:housenumber"];
  if (typeof street === "string" && street.trim()) {
    const line = typeof number === "string" && number.trim() ? `${street} ${number}` : street;
    parts.push(line);
  }
  const city = typeof tags["addr:city"] === "string" ? tags["addr:city"] : "";
  const postcode = typeof tags["addr:postcode"] === "string" ? tags["addr:postcode"] : "";
  const country =
    (typeof tags["addr:country"] === "string" && tags["addr:country"]) ||
    (typeof tags["addr:country_code"] === "string" && tags["addr:country_code"]) ||
    (typeof tags["country"] === "string" && tags["country"]) ||
    "";
  const locality = [postcode, city].filter(Boolean).join(" ");
  if (locality) {
    parts.push(locality);
  }
  if (!parts.length && (city || country)) {
    return [city, country].filter(Boolean).join(", ");
  }
  if (!street && locality && country) {
    parts.push(country);
  }
  return parts.length ? parts.join(", ") : "Address unavailable";
};

const haversineKm = (lat1: number, lon1: number, lat2: number, lon2: number) => {
  const radius = 6371;
  const phi1 = (lat1 * Math.PI) / 180;
  const phi2 = (lat2 * Math.PI) / 180;
  const deltaPhi = ((lat2 - lat1) * Math.PI) / 180;
  const deltaLambda = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(deltaPhi / 2) ** 2 +
    Math.cos(phi1) * Math.cos(phi2) * Math.sin(deltaLambda / 2) ** 2;
  return radius * (2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a)));
};

const normalizeProviders = (
  elements: Array<Record<string, unknown>>,
  originLat: number,
  originLon: number
): TherapistResult[] => {
  const providers: TherapistResult[] = [];
  for (const element of elements) {
    const lat =
      typeof element.lat === "number"
        ? element.lat
        : typeof element.center === "object" && element.center
          ? (element.center as { lat?: number }).lat
          : undefined;
    const lon =
      typeof element.lon === "number"
        ? element.lon
        : typeof element.center === "object" && element.center
          ? (element.center as { lon?: number }).lon
          : undefined;
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
      continue;
    }
    const tags =
      typeof element.tags === "object" && element.tags ? (element.tags as Record<string, unknown>) : {};
    const name =
      (typeof tags.name === "string" && tags.name) ||
      (typeof tags.brand === "string" && tags.brand) ||
      "Therapist";
    const address = formatAddress(tags);
    const phone =
      (typeof tags.phone === "string" && tags.phone) ||
      (typeof tags["contact:phone"] === "string" && tags["contact:phone"]) ||
      "Phone unavailable";
    const website =
      (typeof tags.website === "string" && tags.website) ||
      (typeof tags["contact:website"] === "string" && tags["contact:website"]) ||
      "";
    const type = typeof element.type === "string" ? element.type : "node";
    const id = typeof element.id === "number" ? element.id : 0;
    const osmUrl = `https://www.openstreetmap.org/${type}/${id}`;
    const url = website || osmUrl;
    const distanceKm = haversineKm(originLat, originLon, Number(lat), Number(lon));
    providers.push({
      name,
      address,
      url,
      phone,
      distance_km: Math.round(distanceKm * 100) / 100
    });
  }
  providers.sort((a, b) => a.distance_km - b.distance_km);
  return providers.slice(0, limit);
};

export const searchTherapists = async (query: string, radiusKm?: number) => {
  const trimmedQuery = query.trim();
  if (!trimmedQuery) {
    return [];
  }
  const radius = Number.isFinite(radiusKm) && radiusKm ? radiusKm : defaultRadiusKm;
  if (!allowRequest()) {
    return [];
  }
  try {
    const coords = await geocodeLocation(trimmedQuery);
    if (!coords) {
      return [];
    }
    const [lat, lon] = coords;
    const cacheKey = `${lat.toFixed(3)}:${lon.toFixed(3)}:${radius}`;
    const now = Date.now();
    const cached = cache.get(cacheKey);
    if (cached && cached.expiresAt > now) {
      return cached.results;
    }
    const elements = await overpassSearch(lat, lon, Math.round(radius * 1000));
    const providers = normalizeProviders(elements, lat, lon);
    cache.set(cacheKey, { expiresAt: now + CACHE_TTL_MS, results: providers });
    return providers;
  } catch {
    return [];
  }
};

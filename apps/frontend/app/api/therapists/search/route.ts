import { NextResponse } from "next/server";
import {
  copyCookieHeader,
  getBackendBaseUrl,
  proxyJsonResponse
} from "../../_lib/backend";

export const runtime = "nodejs";

export async function POST(request: Request) {
  let payload: { location?: string; radius_km?: number } = {};
  try {
    payload = (await request.json()) as { location?: string; radius_km?: number };
  } catch {
    return NextResponse.json({ detail: "Invalid JSON" }, { status: 400 });
  }
  const location = typeof payload.location === "string" ? payload.location.trim() : "";
  if (!location) {
    return NextResponse.json({ detail: "Location is required" }, { status: 400 });
  }
  const radiusRaw = payload.radius_km;
  const radius =
    typeof radiusRaw === "number" && Number.isFinite(radiusRaw)
      ? Math.max(1, Math.min(50, radiusRaw))
      : undefined;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json"
  };
  const cookieHeader = copyCookieHeader(request);
  if (cookieHeader) {
    headers.cookie = cookieHeader;
  }

  try {
    const backendRes = await fetch(`${getBackendBaseUrl()}/therapists/search`, {
      method: "POST",
      headers,
      cache: "no-store",
      body: JSON.stringify({
        location,
        radius_km: radius
      })
    });
    return proxyJsonResponse(backendRes);
  } catch {
    return NextResponse.json({ detail: "Backend unavailable" }, { status: 502 });
  }
}

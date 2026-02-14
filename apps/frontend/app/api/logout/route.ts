import { NextResponse } from "next/server";
import {
  copyCookieHeader,
  getBackendBaseUrl,
  proxyJsonResponse
} from "../_lib/backend";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const headers: Record<string, string> = {
    Accept: "application/json"
  };
  const cookieHeader = copyCookieHeader(request);
  if (cookieHeader) {
    headers.cookie = cookieHeader;
  }

  try {
    const response = await fetch(`${getBackendBaseUrl()}/logout`, {
      method: "POST",
      headers,
      cache: "no-store"
    });
    return proxyJsonResponse(response);
  } catch {
    return NextResponse.json({ detail: "Backend unavailable" }, { status: 502 });
  }
}

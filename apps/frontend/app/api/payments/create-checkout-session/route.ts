import { NextResponse } from "next/server";
import {
  copyCookieHeader,
  getBackendBaseUrl,
  proxyJsonResponse
} from "../../_lib/backend";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const headers: Record<string, string> = { Accept: "application/json" };
  const cookieHeader = copyCookieHeader(request);
  if (cookieHeader) {
    headers.cookie = cookieHeader;
  }

  try {
    const backendRes = await fetch(`${getBackendBaseUrl()}/payments/create-checkout-session`, {
      method: "POST",
      headers,
      cache: "no-store"
    });
    return proxyJsonResponse(backendRes);
  } catch {
    return NextResponse.json({ detail: "Backend unavailable" }, { status: 502 });
  }
}

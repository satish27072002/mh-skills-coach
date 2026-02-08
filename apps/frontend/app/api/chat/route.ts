import { NextResponse } from "next/server";
import { defaultResponse } from "../_lib/safety";
import {
  copyCookieHeader,
  getBackendBaseUrl,
  proxyJsonResponse
} from "../_lib/backend";

export const runtime = "nodejs";

export async function POST(request: Request) {
  let payload: { message?: string } = {};
  try {
    payload = (await request.json()) as { message?: string };
  } catch {
    return NextResponse.json({ detail: "Invalid JSON" }, { status: 400 });
  }

  const message = typeof payload.message === "string" ? payload.message.trim() : "";
  if (!message) {
    return NextResponse.json({ detail: "Message is required" }, { status: 400 });
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 15000);

  try {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "application/json"
    };
    const cookieHeader = copyCookieHeader(request);
    if (cookieHeader) {
      headers.cookie = cookieHeader;
    }

    const response = await fetch(`${getBackendBaseUrl()}/chat`, {
      method: "POST",
      headers,
      cache: "no-store",
      body: JSON.stringify({ message }),
      signal: controller.signal
    });
    clearTimeout(timeoutId);
    return proxyJsonResponse(response);
  } catch {
    clearTimeout(timeoutId);
    const fallback = defaultResponse();
    return NextResponse.json(
      {
        ...fallback,
        coach_message: `I could not reach the model right now. ${fallback.coach_message}`
      },
      { status: 502 }
    );
  }
}

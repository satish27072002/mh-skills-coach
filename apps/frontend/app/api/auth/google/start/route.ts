import { NextResponse } from "next/server";

import { getBackendBaseUrl, getSetCookieHeaders } from "../../../_lib/backend";

export const runtime = "nodejs";

export async function GET() {
  try {
    const backendRes = await fetch(`${getBackendBaseUrl()}/auth/google/start`, {
      method: "GET",
      redirect: "manual",
      cache: "no-store"
    });
    const location = backendRes.headers.get("location");
    if (!location) {
      return NextResponse.json({ detail: "Missing redirect location" }, { status: 502 });
    }

    const response = NextResponse.redirect(location, { status: backendRes.status });
    for (const setCookie of getSetCookieHeaders(backendRes.headers)) {
      response.headers.append("set-cookie", setCookie);
    }
    return response;
  } catch {
    return NextResponse.json({ detail: "Backend unavailable" }, { status: 502 });
  }
}

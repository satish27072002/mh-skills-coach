import { NextResponse } from "next/server";

import { getBackendBaseUrl } from "../../../_lib/backend";

export const runtime = "nodejs";

type HeadersWithSetCookie = Headers & {
  getSetCookie?: () => string[];
};

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
    const setCookies = (backendRes.headers as HeadersWithSetCookie).getSetCookie?.() ?? [];
    for (const setCookie of setCookies) {
      response.headers.append("set-cookie", setCookie);
    }
    if (setCookies.length === 0) {
      const setCookie = backendRes.headers.get("set-cookie");
      if (setCookie) {
        response.headers.append("set-cookie", setCookie);
      }
    }
    return response;
  } catch {
    return NextResponse.json({ detail: "Backend unavailable" }, { status: 502 });
  }
}

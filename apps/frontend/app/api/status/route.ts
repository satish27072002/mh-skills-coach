import { NextResponse } from "next/server";
import { getBackendBaseUrl } from "../_lib/backend";

export const runtime = "nodejs";

export async function GET() {
  const backendBase = getBackendBaseUrl();
  try {
    const response = await fetch(`${backendBase}/status`, {
      cache: "no-store",
      headers: { Accept: "application/json" }
    });
    if (!response.ok) {
      throw new Error("backend_unavailable");
    }
    const data = await response.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json(
      {
        agent_mode: "deterministic",
        model: null,
        pgvector_ready: false,
        ollama_reachable: false,
        reason: "Backend unavailable"
      },
      { status: 502 }
    );
  }
}

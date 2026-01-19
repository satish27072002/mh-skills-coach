import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function GET() {
  return NextResponse.json({
    agent_mode: "deterministic",
    model: null,
    pgvector_ready: false,
    ollama_reachable: false,
    reason: "Vercel demo mode"
  });
}

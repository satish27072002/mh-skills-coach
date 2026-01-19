import { NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "../_lib/auth";
import {
  classifyIntent,
  crisisResponse,
  defaultResponse,
  prescriptionResponse,
  therapistCta,
  type ChatResponse
} from "../_lib/safety";
import { searchTherapists } from "../_lib/therapist-search";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }
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

  const intent = classifyIntent(message);
  if (intent === "crisis") {
    return NextResponse.json(crisisResponse());
  }
  if (intent === "prescription") {
    return NextResponse.json(prescriptionResponse());
  }
  if (intent === "therapist_search") {
    if (!session.is_premium) {
      const response: ChatResponse = {
        coach_message: "I can help you find a therapist. Premium is required to unlock the directory.",
        premium_cta: therapistCta()
      };
      return NextResponse.json(response);
    }
    const providers = await searchTherapists(message);
    const response: ChatResponse = {
      coach_message: providers.length
        ? "Here are some nearby therapist options based on what you shared."
        : "I could not find matches for that location. Try adding a city or postcode.",
      therapists: providers
    };
    return NextResponse.json(response);
  }

  return NextResponse.json(defaultResponse());
}

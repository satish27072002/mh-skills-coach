import { NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "../../_lib/auth";
import { searchTherapists } from "../../_lib/therapist-search";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }
  if (!session.is_premium) {
    return NextResponse.json({ detail: "Premium required" }, { status: 403 });
  }
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
  const results = await searchTherapists(location, radius);
  return NextResponse.json({ results });
}

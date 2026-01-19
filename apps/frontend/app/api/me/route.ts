import { NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "../_lib/auth";

export const runtime = "nodejs";

export async function GET() {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }
  return NextResponse.json({
    id: session.user.id,
    email: session.user.email,
    name: session.user.name,
    is_premium: session.is_premium
  });
}

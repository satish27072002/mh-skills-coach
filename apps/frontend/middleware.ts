import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export async function middleware(req: NextRequest) {
  const sessionCookie = req.cookies.get("mh_session");
  const guestCookie = req.cookies.get("mh_guest_session");
  // Allow access if user has either an auth session or a guest session
  if (!sessionCookie?.value && !guestCookie?.value) {
    const loginUrl = req.nextUrl.clone();
    loginUrl.pathname = "/login";
    loginUrl.searchParams.set("redirect", "/");
    return NextResponse.redirect(loginUrl);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/"]
};

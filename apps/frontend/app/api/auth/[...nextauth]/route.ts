import NextAuth from "next-auth";
import { authOptions } from "../../_lib/auth";

export const runtime = "nodejs";

const handler = NextAuth(authOptions);

export { handler as GET, handler as POST };

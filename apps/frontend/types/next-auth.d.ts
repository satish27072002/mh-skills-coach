import type { DefaultSession } from "next-auth";

declare module "next-auth" {
  interface Session {
    is_premium: boolean;
    user: {
      id: string;
      email?: string | null;
      name?: string | null;
    } & DefaultSession["user"];
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    is_premium?: boolean;
  }
}

import type { NextAuthOptions } from "next-auth";
import GoogleProvider from "next-auth/providers/google";

const premiumEmails = (process.env.PREMIUM_EMAILS ?? "")
  .split(",")
  .map((email) => email.trim().toLowerCase())
  .filter(Boolean);

const isPremiumEmail = (email?: string | null) => {
  if (!email) return false;
  if (premiumEmails.length === 0) return true;
  return premiumEmails.includes(email.toLowerCase());
};

export const authOptions: NextAuthOptions = {
  providers: [
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID ?? "",
      clientSecret: process.env.GOOGLE_CLIENT_SECRET ?? ""
    })
  ],
  secret: process.env.NEXTAUTH_SECRET,
  pages: {
    signIn: "/login"
  },
  session: {
    strategy: "jwt"
  },
  callbacks: {
    async jwt({ token }) {
      token.is_premium = isPremiumEmail(token.email);
      return token;
    },
    async session({ session, token }) {
      const id = token.sub ?? token.email ?? "user";
      session.user = {
        ...session.user,
        id,
        email: token.email,
        name: token.name
      };
      session.is_premium = Boolean(token.is_premium);
      return session;
    }
  }
};

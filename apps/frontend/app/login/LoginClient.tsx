"use client";

import { signIn } from "next-auth/react";
import { useSearchParams } from "next/navigation";

export default function LoginClient() {
  const params = useSearchParams();
  const error = params.get("error");
  const redirect = params.get("redirect") || "/";

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-slate-50 text-ink">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white px-8 py-6 text-center shadow-sm">
        <h1 className="font-display text-2xl">Mental Health Skills Coach</h1>
        <p className="mt-2 text-sm text-ink/70">Sign in to continue</p>
        {error && (
          <div className="mt-4 rounded-xl border border-coral/40 bg-coral/10 p-3 text-sm text-ink">
            Google sign-in was canceled or failed. Please try again.
          </div>
        )}
        <button
          className="mt-5 w-full rounded-full bg-ink px-4 py-3 text-sm font-semibold text-white shadow hover:bg-ink/90"
          onClick={() => signIn("google", { callbackUrl: redirect })}
        >
          Continue with Google
        </button>
      </div>
    </main>
  );
}

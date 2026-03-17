"use client";

import { useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import AppShell from "../../components/app-shell";
import { Button } from "../../components/ui/button";

export default function LoginClient() {
  const params = useSearchParams();
  const router = useRouter();
  const error = params.get("error");
  const authStartUrl = "/api/auth/google/start";
  const [guestLoading, setGuestLoading] = useState(false);
  const [guestError, setGuestError] = useState<string | null>(null);

  const startGuestSession = async () => {
    setGuestLoading(true);
    setGuestError(null);
    try {
      const res = await fetch("/api/guest", {
        method: "POST",
        credentials: "include",
        cache: "no-store",
      });
      if (!res.ok) {
        throw new Error("Failed to start guest session");
      }
      router.push("/");
    } catch {
      setGuestError("Could not start guest session. Please try again.");
    } finally {
      setGuestLoading(false);
    }
  };

  return (
    <AppShell>
      <div className="flex flex-1 items-center justify-center px-4">
        <div className="w-full max-w-md border bg-sidebar p-6 shadow-sm">
          <h2 className="font-display text-xl font-semibold">Mental Health Skills Coach</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Sign in with Google for unlimited access, or try as a guest with 15 free prompts.
          </p>

          <div className="mt-6 space-y-4">
            {error && (
              <div className="border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                Google sign-in was canceled or failed. Please try again.
              </div>
            )}
            {guestError && (
              <div className="border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                {guestError}
              </div>
            )}
            <Button
              className="w-full"
              onClick={() => {
                window.location.assign(authStartUrl);
              }}
            >
              Continue with Google
            </Button>
            <div className="flex items-center gap-3">
              <div className="h-px flex-1 bg-border" />
              <span className="text-xs text-muted-foreground">or</span>
              <div className="h-px flex-1 bg-border" />
            </div>
            <Button
              variant="outline"
              className="w-full"
              onClick={startGuestSession}
              disabled={guestLoading}
            >
              {guestLoading ? "Starting..." : "Continue as Guest (15 free prompts)"}
            </Button>
            <p className="text-center text-xs text-muted-foreground">
              Guest sessions are limited to 15 prompts. Sign in for unlimited access.
            </p>
          </div>
        </div>
      </div>
    </AppShell>
  );
}

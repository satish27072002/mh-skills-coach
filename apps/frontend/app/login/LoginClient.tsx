"use client";

import { Sparkles } from "lucide-react";
import { useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Button } from "../../components/ui/button";
import { Separator } from "../../components/ui/separator";

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
        cache: "no-store"
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
    <div className="flex min-h-screen flex-col bg-background">
      {/* Minimal header */}
      <header className="sticky top-0 z-30 border-b bg-card/80 backdrop-blur-lg">
        <div className="mx-auto flex h-14 max-w-3xl items-center px-4">
          <span className="text-sm font-semibold text-primary">MH Skills Coach</span>
        </div>
      </header>

      {/* Centered login card */}
      <main className="flex flex-1 items-center justify-center px-4">
        <div className="w-full max-w-sm space-y-6">
          {/* Icon + heading */}
          <div className="flex flex-col items-center gap-3 text-center">
            <div className="rounded-2xl bg-primary/10 p-4">
              <Sparkles className="h-8 w-8 text-primary" />
            </div>
            <h1 className="text-xl font-semibold text-foreground">Welcome</h1>
            <p className="max-w-xs text-sm text-muted-foreground">
              Practical coping skills, therapist discovery, and booking &mdash; all in one place.
            </p>
          </div>

          {/* Login card */}
          <div className="rounded-2xl border bg-card p-6 shadow-sm">
            <div className="space-y-4">
              {error ? (
                <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300">
                  Google sign-in was canceled or failed. Please try again.
                </div>
              ) : null}
              {guestError ? (
                <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300">
                  {guestError}
                </div>
              ) : null}

              <Button
                className="w-full"
                onClick={() => {
                  window.location.assign(authStartUrl);
                }}
              >
                Continue with Google
              </Button>

              <div className="flex items-center gap-3">
                <Separator className="flex-1" />
                <span className="text-xs text-muted-foreground">or</span>
                <Separator className="flex-1" />
              </div>

              <Button
                variant="outline"
                className="w-full"
                onClick={startGuestSession}
                disabled={guestLoading}
              >
                {guestLoading ? "Starting..." : "Continue as Guest"}
              </Button>

              <p className="text-center text-xs text-muted-foreground">
                Guest sessions have limited prompts. Sign in for full access.
              </p>
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t py-3 text-center text-xs text-muted-foreground">
        Not medical advice. If you are in immediate danger, contact local emergency services.
      </footer>
    </div>
  );
}

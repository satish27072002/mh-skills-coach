"use client";

import { useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import AppShell from "../../components/app-shell";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
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
    <AppShell
      title="Welcome"
      subtitle="Sign in with Google for unlimited access, or try as a guest with 15 free prompts."
    >
      <div className="mx-auto mt-8 w-full max-w-md">
        <Card>
          <CardHeader>
            <CardTitle>Mental Health Skills Coach</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">Sign in to continue</p>
            {error ? (
              <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                Google sign-in was canceled or failed. Please try again.
              </div>
            ) : null}
            {guestError ? (
              <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
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
              {guestLoading ? "Starting..." : "Continue as Guest (15 free prompts)"}
            </Button>
            <p className="text-center text-xs text-muted-foreground">
              Guest sessions are limited to 15 prompts. Sign in for unlimited access.
            </p>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}

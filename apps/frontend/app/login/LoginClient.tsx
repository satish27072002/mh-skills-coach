"use client";

import { useSearchParams } from "next/navigation";
import AppShell from "../../components/app-shell";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";

export default function LoginClient() {
  const params = useSearchParams();
  const error = params.get("error");
  const authStartUrl = "/api/auth/google/start";

  return (
    <AppShell
      title="Welcome back"
      subtitle="Sign in with Google to continue your conversations, premium status, and booking flow."
    >
      <div className="mx-auto mt-8 w-full max-w-md">
        <Card>
          <CardHeader>
            <CardTitle>Mental Health Skills Coach</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted">Sign in to continue</p>
            {error ? (
              <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                Google sign-in was canceled or failed. Please try again.
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
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}

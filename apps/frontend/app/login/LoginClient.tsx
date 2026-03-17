"use client";

import { useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Heart, Shield, MessageCircle } from "lucide-react";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
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
    <div className="flex min-h-screen flex-col lg:flex-row">
      {/* Left panel — branding */}
      <div className="flex flex-1 flex-col items-center justify-center px-8 py-12 lg:px-16">
        <div className="max-w-md space-y-8">
          <div>
            <h1 className="font-display text-4xl font-bold tracking-tight sm:text-5xl">
              MH Skills Coach
            </h1>
            <p className="mt-4 text-lg leading-relaxed text-muted-foreground">
              Practice evidence-based coping skills, discover nearby therapists,
              and take a grounded next step.
            </p>
          </div>

          <div className="space-y-4">
            <div className="flex items-start gap-3">
              <div className="mt-0.5 rounded-lg bg-primary/10 p-2">
                <Heart className="h-4 w-4 text-primary" />
              </div>
              <div>
                <p className="text-sm font-semibold">AI-Guided Coaching</p>
                <p className="text-sm text-muted-foreground">
                  Breathing exercises, grounding techniques, and more.
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <div className="mt-0.5 rounded-lg bg-primary/10 p-2">
                <MessageCircle className="h-4 w-4 text-primary" />
              </div>
              <div>
                <p className="text-sm font-semibold">Therapist Discovery</p>
                <p className="text-sm text-muted-foreground">
                  Find and book providers near you.
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <div className="mt-0.5 rounded-lg bg-primary/10 p-2">
                <Shield className="h-4 w-4 text-primary" />
              </div>
              <div>
                <p className="text-sm font-semibold">Safety First</p>
                <p className="text-sm text-muted-foreground">
                  Crisis detection with immediate emergency resources.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Right panel — auth card */}
      <div className="flex flex-1 items-center justify-center px-8 py-12 lg:px-16">
        <Card className="w-full max-w-sm rounded-2xl shadow-xl">
          <CardHeader className="text-center">
            <CardTitle className="text-2xl">Welcome</CardTitle>
            <CardDescription>
              Sign in for unlimited access, or try as a guest.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {error && (
              <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                Google sign-in was canceled or failed. Please try again.
              </div>
            )}
            {guestError && (
              <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                {guestError}
              </div>
            )}

            <Button
              className="w-full rounded-xl"
              size="lg"
              onClick={() => window.location.assign(authStartUrl)}
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
              className="w-full rounded-xl"
              size="lg"
              onClick={startGuestSession}
              disabled={guestLoading}
            >
              {guestLoading ? "Starting..." : "Continue as Guest"}
            </Button>

            <p className="text-center text-xs text-muted-foreground">
              Guest sessions are limited to 15 prompts.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

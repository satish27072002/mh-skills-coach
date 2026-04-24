"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import AppShell from "../../../components/app-shell";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";

export default function PremiumSuccessPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const sessionId = searchParams.get("session_id");
  const [status, setStatus] = useState<"checking" | "active" | "pending" | "error">("checking");

  useEffect(() => {
    let cancelled = false;
    const verify = async () => {
      if (!sessionId) {
        if (!cancelled) setStatus("active");
        return;
      }
      try {
        const res = await fetch(`/api/payments/session/${sessionId}`, {
          credentials: "include",
          cache: "no-store",
        });
        if (!res.ok) throw new Error("verification_failed");
        const data = await res.json();
        if (cancelled) return;
        if (data.payment_status === "paid") {
          setStatus("active");
          setTimeout(() => {
            router.replace("/");
            router.refresh();
          }, 1200);
          return;
        }
        setStatus("pending");
      } catch {
        if (!cancelled) setStatus("error");
      }
    };
    verify();
    return () => {
      cancelled = true;
    };
  }, [router, sessionId]);

  const description =
    status === "checking"
      ? "We are verifying your payment and activating premium access..."
      : status === "active"
        ? "Your premium access is now active. Redirecting you back to chat..."
        : status === "pending"
          ? "Your checkout completed, but payment confirmation is still processing. Please wait a moment and go back to chat."
          : "We could not verify your payment automatically. Please go back to chat and refresh your account status.";

  return (
    <AppShell>
      <div className="flex flex-1 items-center justify-center px-4">
        <Card className="w-full max-w-xl">
          <CardHeader>
            <CardTitle>{status === "active" ? "Premium Active" : "Verifying payment"}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-muted-foreground">{description}</p>
            <Link
              href="/"
              className="inline-flex h-10 items-center justify-center rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary/90"
            >
              Back to chat
            </Link>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}

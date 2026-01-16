"use client";

import { useEffect, useMemo, useState } from "react";

const defaultApiBase =
  typeof window === "undefined"
    ? "http://backend:8000"
    : window.location.hostname === "localhost"
      ? "http://localhost:8000"
      : "http://backend:8000";

const envApiBase =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE ||
  "";

const resolveApiBase = () => {
  let base = envApiBase || defaultApiBase;
  if (
    typeof window !== "undefined" &&
    window.location.hostname === "localhost" &&
    base.includes("backend:8000")
  ) {
    base = "http://localhost:8000";
  }
  return base;
};

export default function PremiumSuccessPage() {
  const apiBase = useMemo(resolveApiBase, []);
  const [status, setStatus] = useState<"checking" | "paid" | "unpaid" | "error">("checking");

  useEffect(() => {
    const sessionId =
      typeof window !== "undefined"
        ? new URLSearchParams(window.location.search).get("session_id")
        : null;
    if (!sessionId) {
      setStatus("error");
      return;
    }
    const verify = async () => {
      try {
        const res = await fetch(`${apiBase}/payments/session/${sessionId}`, {
          credentials: "include"
        });
        if (!res.ok) {
          throw new Error("verify_failed");
        }
        const data = await res.json();
        setStatus(data.payment_status === "paid" ? "paid" : "unpaid");
      } catch {
        setStatus("error");
      }
    };
    verify();
  }, [apiBase]);

  return (
    <main className="min-h-screen bg-slate-50 px-6 py-16 text-ink">
      <div className="mx-auto max-w-xl space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="font-display text-2xl">Premium unlocked</h1>
        {status === "checking" && <p>Checking payment status...</p>}
        {status === "paid" && <p>Your payment is confirmed. You now have premium access.</p>}
        {status === "unpaid" && <p>Your payment is still processing. Please refresh in a moment.</p>}
        {status === "error" && <p>We could not verify the payment. Please contact support.</p>}
        <a className="text-sm font-semibold text-ink underline" href="/">
          Back to chat
        </a>
      </div>
    </main>
  );
}

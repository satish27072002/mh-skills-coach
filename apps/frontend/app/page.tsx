"use client";

import { ArrowUp, Loader2, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import AppShell from "../components/app-shell";
import ChatBubble from "../components/ChatBubble";
import StatusBadge from "../components/StatusBadge";
import ThemeToggle from "../components/theme-toggle";
import UserMenu from "../components/user-menu";
import type { ChatResponse, Message } from "../components/chat-types";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "../components/ui/dialog";
import { Input } from "../components/ui/input";
import { Separator } from "../components/ui/separator";
import { Textarea } from "../components/ui/textarea";

export default function Home() {
  const router = useRouter();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [authStatus, setAuthStatus] = useState<"loading" | "ready">("loading");
  const [premiumStatus, setPremiumStatus] = useState<"unknown" | "free" | "premium">("unknown");
  const [checkoutLoading, setCheckoutLoading] = useState(false);
  const [therapistModalOpen, setTherapistModalOpen] = useState(false);
  const [therapistLocation, setTherapistLocation] = useState("");
  const [therapistRadius, setTherapistRadius] = useState("");
  const [therapistResults, setTherapistResults] = useState<ChatResponse["therapists"]>([]);
  const [therapistError, setTherapistError] = useState<string | null>(null);
  const [therapistLoading, setTherapistLoading] = useState(false);
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, isSending]);

  useEffect(() => {
    let cancelled = false;
    const loadMe = async () => {
      if (!cancelled) {
        setAuthStatus("loading");
      }
      try {
        const res = await fetch("/api/me", { credentials: "include" });
        if (res.status === 401) {
          if (!cancelled) {
            setIsAuthenticated(false);
            setPremiumStatus("free");
          }
          const params = new URLSearchParams(window.location.search);
          const authError = params.get("auth_error");
          const nextLoginUrl = authError ? `/login?error=${encodeURIComponent(authError)}` : "/login";
          router.replace(nextLoginUrl);
          return;
        }
        if (!res.ok) {
          throw new Error("me_failed");
        }
        const data = await res.json();
        if (!cancelled) {
          setIsAuthenticated(true);
          setPremiumStatus(data.is_premium ? "premium" : "free");
          setAuthStatus("ready");
        }
      } catch {
        if (!cancelled) {
          setIsAuthenticated(false);
          setPremiumStatus("free");
          setError("Unable to load account status. Premium actions may be unavailable.");
          setAuthStatus("ready");
        }
      }
    };
    loadMe();
    return () => {
      cancelled = true;
    };
  }, [router]);

  const startCheckout = async () => {
    if (!isAuthenticated) {
      setError("Please sign in to continue.");
      toast.error("Please sign in to continue.");
      return;
    }
    setCheckoutLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/payments/create-checkout-session", {
        method: "POST",
        credentials: "include"
      });
      if (!res.ok) {
        throw new Error("checkout_failed");
      }
      const data = await res.json();
      if (data?.url) {
        window.location.assign(data.url);
      } else {
        throw new Error("checkout_failed");
      }
    } catch {
      setError("Unable to start checkout. Please try again.");
      toast.error("Unable to start checkout. Please try again.");
    } finally {
      setCheckoutLoading(false);
    }
  };

  const sendMessage = async (rawMessage: string) => {
    const trimmed = rawMessage.trim();
    if (!trimmed || isSending) {
      return;
    }

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: trimmed
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsSending(true);
    setError(null);
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ message: trimmed })
      });
      if (!res.ok) {
        throw new Error("Request failed");
      }
      const data = (await res.json()) as ChatResponse;
      const assistantMsg: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: data.coach_message,
        booking_proposal: data.booking_proposal,
        requires_confirmation: data.requires_confirmation,
        exercise: data.exercise,
        resources: data.resources,
        therapists: data.therapists,
        sources: data.sources,
        premium_cta: data.premium_cta,
        risk_level: data.risk_level
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Something went wrong";
      const uiMessage = message === "Failed to fetch" ? "Failed to reach the API." : message;
      setError(uiMessage);
      toast.error(uiMessage);
    } finally {
      setIsSending(false);
    }
  };

  const handleSend = async () => {
    const trimmed = input.trim();
    if (!trimmed) {
      return;
    }
    setInput("");
    await sendMessage(trimmed);
  };

  const handleBookingAction = async (action: "YES" | "NO") => {
    await sendMessage(action);
  };

  const handleTherapistSearch = async () => {
    if (premiumStatus !== "premium") {
      return;
    }
    if (!therapistLocation.trim()) {
      const message = "Please enter a city or postcode.";
      setTherapistError(message);
      return;
    }
    setTherapistLoading(true);
    setTherapistError(null);
    const radiusValue = therapistRadius ? Number(therapistRadius) : undefined;
    const radius = Number.isFinite(radiusValue) ? radiusValue : undefined;
    try {
      const res = await fetch("/api/therapists/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          location: therapistLocation.trim(),
          radius_km: radius
        })
      });
      if (!res.ok) {
        throw new Error("Search failed.");
      }
      const data = (await res.json()) as { results: ChatResponse["therapists"] };
      setTherapistResults(data.results || []);
      if (!data.results || data.results.length === 0) {
        toast.message("No providers found for that area.");
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Search failed.";
      setTherapistError(message);
      toast.error(message);
    } finally {
      setTherapistLoading(false);
    }
  };

  if (authStatus === "loading") {
    return (
      <main className="flex min-h-screen items-center justify-center px-4">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle>Mental Health Skills Coach</CardTitle>
          </CardHeader>
          <CardContent className="flex items-center gap-2 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" />
            Checking session…
          </CardContent>
        </Card>
      </main>
    );
  }

  return (
    <AppShell
      title="Steadying routines, one chat at a time"
      subtitle="Practical support, therapist discovery, and confirmation-based booking emails in one flow."
      actions={
        <>
          <StatusBadge />
          <ThemeToggle />
          <Button
            variant={premiumStatus === "premium" ? "default" : "secondary"}
            size="sm"
            onClick={() => {
              if (premiumStatus === "premium") {
                setTherapistModalOpen(true);
                setTherapistResults([]);
                setTherapistError(null);
              } else {
                startCheckout();
              }
            }}
            disabled={checkoutLoading || premiumStatus === "unknown"}
          >
            <Search className="h-4 w-4" />
            {premiumStatus === "premium" ? "Find a therapist" : "Get Premium to find a therapist"}
          </Button>
          {premiumStatus === "premium" ? (
            <Badge variant="success">Premium Active</Badge>
          ) : (
            <Button
              variant="default"
              size="sm"
              onClick={startCheckout}
              disabled={checkoutLoading || premiumStatus === "unknown"}
            >
              {checkoutLoading ? "Opening..." : premiumStatus === "unknown" ? "Checking..." : "Get Premium"}
            </Button>
          )}
          <UserMenu
            isAuthenticated={isAuthenticated}
            isPremium={premiumStatus === "premium"}
            onUpgrade={startCheckout}
          />
        </>
      }
    >
      {error ? (
        <Card className="mb-4 border-red-200 bg-red-50 dark:border-red-900/70 dark:bg-red-950/30">
          <CardContent className="p-3 text-sm text-red-700 dark:text-red-300">{error}</CardContent>
        </Card>
      ) : null}

      <Card className="flex min-h-[56vh] flex-1 flex-col">
        <CardContent className="flex h-full flex-1 flex-col gap-4 p-4 sm:p-5">
          <div ref={listRef} className="flex-1 overflow-y-auto rounded-lg border bg-surface/80 p-3">
            {messages.length === 0 ? (
              <div className="flex h-full items-center justify-center text-center text-sm text-muted">
                Share how you are feeling, and I will suggest a grounded next step.
              </div>
            ) : null}
            <div className="space-y-4">
              {messages.map((msg) => (
                <ChatBubble
                  key={msg.id}
                  message={msg}
                  onBookingAction={handleBookingAction}
                  bookingActionDisabled={isSending}
                />
              ))}
              {isSending ? (
                <div className="flex items-center gap-2 text-sm text-muted">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Thinking...
                </div>
              ) : null}
            </div>
          </div>

          <Separator />

          <div className="space-y-2">
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              rows={3}
              className="resize-none"
              placeholder="I feel anxious right now..."
            />
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-muted">Enter to send, Shift+Enter for newline</span>
              <Button onClick={handleSend} disabled={isSending || !input.trim()}>
                {isSending ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Thinking...
                  </>
                ) : (
                  <>
                    <ArrowUp className="h-4 w-4" />
                    Send
                  </>
                )}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Dialog open={therapistModalOpen} onOpenChange={setTherapistModalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Therapist search</DialogTitle>
            <DialogDescription>Search local providers by city/postcode and optional radius.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-[0.15em] text-muted">City or postcode</label>
              <Input value={therapistLocation} onChange={(e) => setTherapistLocation(e.target.value)} placeholder="Stockholm" />
            </div>
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-[0.15em] text-muted">Radius (km, optional)</label>
              <Input value={therapistRadius} onChange={(e) => setTherapistRadius(e.target.value)} placeholder="10" />
            </div>

            {therapistError ? (
              <div className="rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                {therapistError}
              </div>
            ) : null}

            <div className="flex justify-end">
              {premiumStatus === "premium" ? (
                <Button onClick={handleTherapistSearch} disabled={therapistLoading}>
                  {therapistLoading ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Searching...
                    </>
                  ) : (
                    "Search"
                  )}
                </Button>
              ) : (
                <Button onClick={startCheckout} disabled={checkoutLoading}>
                  {checkoutLoading ? "Opening..." : "Get Premium"}
                </Button>
              )}
            </div>

            {therapistResults && therapistResults.length > 0 ? (
              <div className="space-y-2">
                <p className="text-xs font-semibold uppercase tracking-[0.15em] text-muted">Results</p>
                <ul className="space-y-2 text-sm">
                  {therapistResults.map((therapist) => {
                    const link = therapist.source_url || therapist.url;
                    return (
                      <li key={`${therapist.name}-${therapist.address}`} className="rounded-lg border p-3">
                        {link ? (
                          <a className="font-semibold underline" href={link} target="_blank" rel="noreferrer">
                            {therapist.name}
                          </a>
                        ) : (
                          <p className="font-semibold">{therapist.name}</p>
                        )}
                        <p className="text-foreground/70">{therapist.address}</p>
                        <p className="text-foreground/70">Distance: {therapist.distance_km} km</p>
                        {therapist.phone ? <p className="text-foreground/70">Phone: {therapist.phone}</p> : null}
                        {therapist.email ? <p className="text-foreground/70">Email: {therapist.email}</p> : null}
                      </li>
                    );
                  })}
                </ul>
              </div>
            ) : null}
          </div>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}

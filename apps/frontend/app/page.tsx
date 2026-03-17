"use client";

import { ArrowUp, Loader2, Search, Sparkles } from "lucide-react";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "../components/ui/dialog";
import { Input } from "../components/ui/input";
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
  const [isGuest, setIsGuest] = useState(false);
  const [guestPromptsRemaining, setGuestPromptsRemaining] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  /* Auto-scroll to bottom on new messages */
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isSending]);

  /* Auth check on mount */
  useEffect(() => {
    let cancelled = false;
    const loadMe = async () => {
      if (!cancelled) {
        setAuthStatus("loading");
      }
      try {
        const res = await fetch("/api/me", { credentials: "include", cache: "no-store" });
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
          if (data.is_guest) {
            setIsGuest(true);
            setIsAuthenticated(false);
            setPremiumStatus("free");
            setGuestPromptsRemaining(data.guest_prompts_remaining ?? null);
          } else {
            setIsAuthenticated(true);
            setPremiumStatus(data.is_premium ? "premium" : "free");
          }
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
        credentials: "include",
        cache: "no-store"
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
        cache: "no-store",
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
      if (isGuest && data.guest_prompts_remaining != null) {
        setGuestPromptsRemaining(data.guest_prompts_remaining);
      }
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
      setTherapistError("Please enter a city or postcode.");
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
        cache: "no-store",
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

  /* ── Loading state ── */
  if (authStatus === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
          <p className="text-sm text-muted-foreground">Loading your session...</p>
        </div>
      </div>
    );
  }

  const guestLimitReached = isGuest && guestPromptsRemaining === 0;
  const inputDisabled = guestLimitReached;

  return (
    <AppShell
      title="MH Skills Coach"
      actions={
        <>
          <StatusBadge />
          <ThemeToggle />
          {isGuest && guestPromptsRemaining != null ? (
            <Badge variant={guestPromptsRemaining <= 3 ? "destructive" : "secondary"}>
              {guestPromptsRemaining} left
            </Badge>
          ) : null}
          {isGuest ? (
            <Button variant="default" size="sm" onClick={() => router.push("/login")}>
              Sign in
            </Button>
          ) : (
            <>
              {premiumStatus === "premium" ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setTherapistModalOpen(true);
                    setTherapistResults([]);
                    setTherapistError(null);
                  }}
                >
                  <Search className="h-3.5 w-3.5" />
                  Find therapist
                </Button>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={startCheckout}
                  disabled={checkoutLoading || premiumStatus === "unknown"}
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  {checkoutLoading ? "Opening..." : "Get Premium"}
                </Button>
              )}
              {premiumStatus === "premium" ? (
                <Badge variant="success">Premium</Badge>
              ) : null}
            </>
          )}
          <UserMenu
            isAuthenticated={isAuthenticated}
            isPremium={premiumStatus === "premium"}
            isGuest={isGuest}
            onUpgrade={startCheckout}
          />
        </>
      }
    >
      {/* ── Full-height chat area ── */}
      <div className="relative mx-auto flex w-full max-w-3xl flex-1 flex-col px-4">

        {/* Error banner */}
        {error ? (
          <div className="mb-3 mt-2 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300">
            {error}
          </div>
        ) : null}

        {/* Guest limit banner */}
        {guestLimitReached ? (
          <div className="mb-3 mt-2 flex items-center justify-between gap-3 rounded-xl border border-warning/30 bg-warning/5 px-4 py-2.5 text-sm">
            <span className="text-muted-foreground">You&apos;ve used all free prompts. Sign in for unlimited access.</span>
            <Button size="sm" variant="default" onClick={() => router.push("/login")}>
              Sign in
            </Button>
          </div>
        ) : null}

        {/* ── Message list ── */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto py-4">
          {messages.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
              <div className="rounded-2xl bg-primary/10 p-4">
                <Sparkles className="h-8 w-8 text-primary" />
              </div>
              <div className="space-y-1.5">
                <h2 className="text-lg font-semibold text-foreground">How are you feeling today?</h2>
                <p className="max-w-sm text-sm text-muted-foreground">
                  Share what&apos;s on your mind and I&apos;ll suggest a grounded next step &mdash; a breathing exercise, coping strategy, or help finding a therapist.
                </p>
              </div>
              <div className="mt-2 flex flex-wrap justify-center gap-2">
                {["I feel anxious", "I'm stressed about work", "Help me find a therapist"].map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    className="rounded-full border bg-card px-3.5 py-1.5 text-sm text-muted-foreground transition-colors hover:border-primary/40 hover:bg-primary/5 hover:text-foreground"
                    onClick={() => {
                      setInput(prompt);
                    }}
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          ) : (
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
                <div className="flex justify-start">
                  <div className="flex items-center gap-2 rounded-2xl rounded-bl-md border bg-card px-4 py-3 text-sm text-muted-foreground shadow-sm">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Thinking...
                  </div>
                </div>
              ) : null}
            </div>
          )}
        </div>

        {/* ── Bottom-anchored input ── */}
        <div className="sticky bottom-0 border-t bg-background pb-4 pt-3">
          <div className="relative">
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              rows={1}
              className="min-h-[48px] resize-none rounded-xl border bg-card py-3 pl-4 pr-12 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:ring-1 focus-visible:ring-primary/40"
              placeholder={inputDisabled ? "Guest limit reached — sign in for unlimited access" : "Message MH Skills Coach..."}
              disabled={inputDisabled}
            />
            <Button
              type="button"
              size="icon"
              className="absolute bottom-1.5 right-1.5 h-9 w-9 rounded-lg"
              onClick={handleSend}
              disabled={isSending || !input.trim() || inputDisabled}
            >
              {isSending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ArrowUp className="h-4 w-4" />
              )}
            </Button>
          </div>
          <p className="mt-1.5 text-center text-xs text-muted-foreground">
            {isGuest && guestPromptsRemaining != null
              ? `${guestPromptsRemaining} prompt${guestPromptsRemaining !== 1 ? "s" : ""} remaining`
              : "Not medical advice. Press Enter to send."}
          </p>
        </div>
      </div>

      {/* ── Therapist search modal ── */}
      <Dialog open={therapistModalOpen} onOpenChange={setTherapistModalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Find a therapist</DialogTitle>
            <DialogDescription>Search local providers by city or postcode.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">City or postcode</label>
              <Input value={therapistLocation} onChange={(e) => setTherapistLocation(e.target.value)} placeholder="Stockholm" />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Radius (km, optional)</label>
              <Input value={therapistRadius} onChange={(e) => setTherapistRadius(e.target.value)} placeholder="10" />
            </div>

            {therapistError ? (
              <div className="rounded-lg border border-red-200 bg-red-50 p-2.5 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300">
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
                <p className="text-xs font-medium text-muted-foreground">Results</p>
                <ul className="space-y-2 text-sm">
                  {therapistResults.map((therapist) => {
                    const link = therapist.source_url || therapist.url;
                    return (
                      <li key={`${therapist.name}-${therapist.address}`} className="rounded-lg border bg-card p-3">
                        {link ? (
                          <a className="font-semibold text-primary underline underline-offset-2" href={link} target="_blank" rel="noreferrer">
                            {therapist.name}
                          </a>
                        ) : (
                          <p className="font-semibold">{therapist.name}</p>
                        )}
                        <p className="mt-0.5 text-muted-foreground">{therapist.address}</p>
                        <p className="text-muted-foreground">{therapist.distance_km} km away</p>
                        {therapist.phone ? <p className="text-muted-foreground">Phone: {therapist.phone}</p> : null}
                        {therapist.email ? <p className="text-muted-foreground">Email: {therapist.email}</p> : null}
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

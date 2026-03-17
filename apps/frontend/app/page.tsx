"use client";

import { ArrowUp, Loader2, MessageSquarePlus, Moon, Search, Sun } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import AppShell from "../components/app-shell";
import ChatBubble from "../components/ChatBubble";
import StatusBadge from "../components/StatusBadge";
import UserMenu from "../components/user-menu";
import type { ChatResponse, Message } from "../components/chat-types";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";

type Theme = "light" | "dark";

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "dark") {
    root.classList.add("dark");
  } else {
    root.classList.remove("dark");
  }
}

function SidebarThemeToggle() {
  const [theme, setThemeState] = useState<Theme>("light");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const saved = window.localStorage.getItem("theme");
    const t: Theme = saved === "dark" ? "dark" : "light";
    setThemeState(t);
    applyTheme(t);
    setMounted(true);
  }, []);

  if (!mounted) return null;

  const toggle = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setThemeState(next);
    applyTheme(next);
    window.localStorage.setItem("theme", next);
  };

  const isDark = theme === "dark";
  return (
    <button
      onClick={toggle}
      className="flex w-full items-center gap-3 px-4 py-2 text-sm text-muted-foreground hover:bg-accent/10 hover:text-foreground"
    >
      {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      {isDark ? "Light mode" : "Dark mode"}
    </button>
  );
}

const STARTER_PROMPTS = [
  "I feel anxious right now",
  "Help me with a breathing exercise",
  "I need to talk about stress at work",
  "How can I improve my sleep?",
];

export default function Home() {
  const router = useRouter();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isGuest, setIsGuest] = useState(false);
  const [guestPromptsRemaining, setGuestPromptsRemaining] = useState<number | null>(null);
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
      if (!cancelled) setAuthStatus("loading");
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
        if (!res.ok) throw new Error("me_failed");
        const data = await res.json();
        if (!cancelled) {
          if (data.is_guest) {
            setIsGuest(true);
            setIsAuthenticated(false);
            setGuestPromptsRemaining(data.guest_prompts_remaining ?? null);
            setPremiumStatus("free");
          } else {
            setIsAuthenticated(true);
            setIsGuest(false);
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
    return () => { cancelled = true; };
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
        cache: "no-store",
      });
      if (!res.ok) throw new Error("checkout_failed");
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
    if (!trimmed || isSending) return;

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: trimmed,
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
        body: JSON.stringify({ message: trimmed }),
      });
      if (!res.ok) throw new Error("Request failed");
      const data = (await res.json()) as ChatResponse;
      if (isGuest && data.guest_prompts_remaining != null) {
        setGuestPromptsRemaining(data.guest_prompts_remaining);
      }
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
        risk_level: data.risk_level,
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
    if (!trimmed) return;
    setInput("");
    await sendMessage(trimmed);
  };

  const handleBookingAction = async (action: "YES" | "NO") => {
    await sendMessage(action);
  };

  const handleNewChat = () => {
    setMessages([]);
    setError(null);
    setInput("");
  };

  const handleTherapistSearch = async () => {
    if (premiumStatus !== "premium") return;
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
        body: JSON.stringify({ location: therapistLocation.trim(), radius_km: radius }),
      });
      if (!res.ok) throw new Error("Search failed.");
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
      <main className="flex min-h-screen items-center justify-center bg-background px-4">
        <div className="w-full max-w-md border bg-card p-6 shadow-sm">
          <h2 className="font-display text-xl font-semibold">Mental Health Skills Coach</h2>
          <div className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Checking session...
          </div>
        </div>
      </main>
    );
  }

  const sidebarContent = (
    <div className="flex flex-1 flex-col">
      {/* Brand */}
      <div className="border-b px-4 py-4">
        <h1 className="font-display text-base font-semibold">MH Skills Coach</h1>
        <p className="mt-0.5 text-xs text-muted-foreground">Coping skills &amp; therapist discovery</p>
      </div>

      {/* Actions */}
      <div className="flex-1 space-y-1 px-2 py-3">
        <button
          onClick={handleNewChat}
          className="flex w-full items-center gap-3 px-4 py-2 text-sm text-muted-foreground hover:bg-accent/10 hover:text-foreground"
        >
          <MessageSquarePlus className="h-4 w-4" />
          New chat
        </button>

        <button
          onClick={() => {
            if (premiumStatus === "premium") {
              setTherapistModalOpen(true);
              setTherapistResults([]);
              setTherapistError(null);
            } else if (isGuest) {
              router.push("/login");
            } else {
              startCheckout();
            }
          }}
          disabled={checkoutLoading || premiumStatus === "unknown"}
          className="flex w-full items-center gap-3 px-4 py-2 text-sm text-muted-foreground hover:bg-accent/10 hover:text-foreground disabled:opacity-50"
        >
          <Search className="h-4 w-4" />
          {premiumStatus === "premium" ? "Find a therapist" : "Find a therapist (Premium)"}
        </button>

        {premiumStatus === "premium" ? (
          <div className="px-4 py-2">
            <Badge variant="success">Premium Active</Badge>
          </div>
        ) : isGuest ? (
          <button
            onClick={() => router.push("/login")}
            className="flex w-full items-center gap-3 px-4 py-2 text-sm text-muted-foreground hover:bg-accent/10 hover:text-foreground"
          >
            Sign in with Google
          </button>
        ) : (
          <button
            onClick={startCheckout}
            disabled={checkoutLoading || premiumStatus === "unknown"}
            className="flex w-full items-center gap-3 px-4 py-2 text-sm text-muted-foreground hover:bg-accent/10 hover:text-foreground disabled:opacity-50"
          >
            {checkoutLoading ? "Opening..." : "Get Premium"}
          </button>
        )}

        <SidebarThemeToggle />

        <div className="px-4 py-2">
          <StatusBadge />
        </div>
      </div>

      {/* Bottom section */}
      <div className="border-t px-2 py-3 space-y-1">
        {isGuest && guestPromptsRemaining != null && (
          <div className="px-4 py-1">
            <Badge variant={guestPromptsRemaining > 5 ? "secondary" : guestPromptsRemaining > 0 ? "warning" : "destructive"}>
              {guestPromptsRemaining} prompt{guestPromptsRemaining !== 1 ? "s" : ""} left
            </Badge>
          </div>
        )}
        <div className="px-2">
          <UserMenu
            isAuthenticated={isAuthenticated}
            isPremium={premiumStatus === "premium"}
            isGuest={isGuest}
            onUpgrade={isGuest ? () => router.push("/login") : startCheckout}
          />
        </div>
      </div>
    </div>
  );

  return (
    <AppShell sidebar={sidebarContent}>
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Error banner */}
        {error && (
          <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700 dark:border-red-900/70 dark:bg-red-950/30 dark:text-red-300">
            {error}
          </div>
        )}

        {/* Chat messages area */}
        <div ref={listRef} className="flex-1 overflow-y-auto px-4 py-6">
          {messages.length === 0 ? (
            <div className="mx-auto flex h-full max-w-2xl flex-col items-center justify-center text-center">
              <h2 className="font-display text-2xl font-semibold">How are you feeling today?</h2>
              <p className="mt-2 text-sm text-muted-foreground">
                Share how you are feeling, and I will suggest a grounded next step.
              </p>
              <div className="mt-6 grid w-full grid-cols-1 gap-2 sm:grid-cols-2">
                {STARTER_PROMPTS.map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => sendMessage(prompt)}
                    className="border bg-card px-4 py-3 text-left text-sm text-foreground hover:bg-accent/10"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-4">
              {messages.map((msg) => (
                <ChatBubble
                  key={msg.id}
                  message={msg}
                  onBookingAction={handleBookingAction}
                  bookingActionDisabled={isSending}
                />
              ))}
              {isSending && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Thinking...
                </div>
              )}
            </div>
          )}
        </div>

        {/* Guest limit banner */}
        {isGuest && guestPromptsRemaining != null && guestPromptsRemaining <= 0 && (
          <div className="border-t border-amber-200 bg-amber-50 px-4 py-3 dark:border-amber-900/70 dark:bg-amber-950/30">
            <div className="mx-auto flex max-w-3xl items-center justify-between gap-3">
              <p className="text-sm text-amber-800 dark:text-amber-200">
                You have used all 15 guest prompts. Sign in for unlimited access.
              </p>
              <Button size="sm" onClick={() => router.push("/login")}>
                Sign in
              </Button>
            </div>
          </div>
        )}

        {/* Input area */}
        <div className="border-t bg-card px-4 py-3">
          <div className="mx-auto max-w-3xl">
            <div className="flex items-end gap-2">
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
                className="min-h-[44px] flex-1 resize-none"
                placeholder="Message MH Skills Coach..."
                disabled={isGuest && guestPromptsRemaining != null && guestPromptsRemaining <= 0}
              />
              <Button
                onClick={handleSend}
                disabled={isSending || !input.trim() || (isGuest && guestPromptsRemaining != null && guestPromptsRemaining <= 0)}
                size="icon"
                className="h-[44px] w-[44px] shrink-0"
              >
                {isSending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
              </Button>
            </div>
            <p className="mt-1.5 text-xs text-muted-foreground">
              {isGuest && guestPromptsRemaining != null
                ? `${guestPromptsRemaining} prompt${guestPromptsRemaining !== 1 ? "s" : ""} remaining`
                : "Not medical advice. If in danger, contact emergency services."}
            </p>
          </div>
        </div>
      </div>

      {/* Therapist search modal */}
      <Dialog open={therapistModalOpen} onOpenChange={setTherapistModalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Therapist search</DialogTitle>
            <DialogDescription>Search local providers by city/postcode and optional radius.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-[0.15em] text-muted-foreground">
                City or postcode
              </label>
              <Input value={therapistLocation} onChange={(e) => setTherapistLocation(e.target.value)} placeholder="Stockholm" />
            </div>
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-[0.15em] text-muted-foreground">
                Radius (km, optional)
              </label>
              <Input value={therapistRadius} onChange={(e) => setTherapistRadius(e.target.value)} placeholder="10" />
            </div>

            {therapistError && (
              <div className="border border-red-200 bg-red-50 p-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                {therapistError}
              </div>
            )}

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

            {therapistResults && therapistResults.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-semibold uppercase tracking-[0.15em] text-muted-foreground">Results</p>
                <ul className="space-y-2 text-sm">
                  {therapistResults.map((therapist) => {
                    const link = therapist.source_url || therapist.url;
                    return (
                      <li key={`${therapist.name}-${therapist.address}`} className="border p-3">
                        {link ? (
                          <a className="font-semibold underline" href={link} target="_blank" rel="noreferrer">
                            {therapist.name}
                          </a>
                        ) : (
                          <p className="font-semibold">{therapist.name}</p>
                        )}
                        <p className="text-foreground/70">{therapist.address}</p>
                        <p className="text-foreground/70">Distance: {therapist.distance_km} km</p>
                        {therapist.phone && <p className="text-foreground/70">Phone: {therapist.phone}</p>}
                        {therapist.email && <p className="text-foreground/70">Email: {therapist.email}</p>}
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}

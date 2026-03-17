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
import { Card } from "../components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";

/* ────────────────────────────────────────────────────── */
/*  Theme toggle (sidebar variant)                        */
/* ────────────────────────────────────────────────────── */

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
    <Button
      variant="ghost"
      onClick={toggle}
      className="w-full justify-start gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground hover:text-foreground"
    >
      {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      {isDark ? "Light mode" : "Dark mode"}
    </Button>
  );
}

/* ────────────────────────────────────────────────────── */
/*  Constants                                             */
/* ────────────────────────────────────────────────────── */

const STARTER_PROMPTS = [
  "I feel anxious right now",
  "Help me with a breathing exercise",
  "I need to talk about stress at work",
  "How can I improve my sleep?",
];

/* ────────────────────────────────────────────────────── */
/*  Main page component                                   */
/* ────────────────────────────────────────────────────── */

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
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const isGuestLimitReached = isGuest && guestPromptsRemaining != null && guestPromptsRemaining <= 0;

  /* Auto-scroll to bottom on new messages */
  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, isSending]);

  /* Auth check on mount */
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

  /* ── Actions ── */

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

  /* ── Shared input bar renderer ── */

  const renderInputBar = () => (
    <div className="input-bar-depth flex items-end gap-2 rounded-2xl px-4 py-3">
      <Textarea
        ref={textareaRef}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSend();
          }
        }}
        rows={1}
        className="min-h-[44px] flex-1 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
        placeholder="Message MH Skills Coach..."
        disabled={isGuestLimitReached}
      />
      <Button
        onClick={handleSend}
        disabled={isSending || !input.trim() || isGuestLimitReached}
        size="icon"
        className="h-10 w-10 shrink-0 rounded-xl"
      >
        {isSending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
      </Button>
    </div>
  );

  const renderInputHint = () => (
    <p className="mt-2 text-center text-xs text-muted-foreground">
      {isGuest && guestPromptsRemaining != null
        ? `${guestPromptsRemaining} prompt${guestPromptsRemaining !== 1 ? "s" : ""} remaining`
        : "Not medical advice. If in danger, contact emergency services."}
    </p>
  );

  /* ── Loading state ── */
  if (authStatus === "loading") {
    return (
      <main className="flex min-h-screen items-center justify-center px-4">
        <Card className="w-full max-w-md p-8">
          <h2 className="font-display text-xl font-semibold">MH Skills Coach</h2>
          <div className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Checking session...
          </div>
        </Card>
      </main>
    );
  }

  /* ── Sidebar content ── */
  const sidebarContent = (
    <div className="flex flex-1 flex-col">
      {/* Brand */}
      <div className="border-b px-5 py-5">
        <h1 className="font-display text-lg font-bold tracking-tight">MH Skills Coach</h1>
        <p className="mt-1 text-xs text-muted-foreground">Coping skills &amp; therapist discovery</p>
      </div>

      {/* Actions */}
      <div className="flex-1 space-y-1 px-3 py-4">
        <Button
          variant="ghost"
          onClick={handleNewChat}
          className="w-full justify-start gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground hover:text-foreground"
        >
          <MessageSquarePlus className="h-4 w-4" />
          New chat
        </Button>

        <Button
          variant="ghost"
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
          className="w-full justify-start gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground hover:text-foreground"
        >
          <Search className="h-4 w-4" />
          Find a therapist
          {premiumStatus !== "premium" && (
            <Badge variant="secondary" className="ml-auto text-[10px]">Premium</Badge>
          )}
        </Button>

        {premiumStatus === "premium" ? (
          <div className="px-3 py-2">
            <Badge variant="success">Premium Active</Badge>
          </div>
        ) : isGuest ? (
          <Button
            variant="ghost"
            onClick={() => router.push("/login")}
            className="w-full justify-start gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground hover:text-foreground"
          >
            Sign in with Google
          </Button>
        ) : (
          <Button
            variant="ghost"
            onClick={startCheckout}
            disabled={checkoutLoading || premiumStatus === "unknown"}
            className="w-full justify-start gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground hover:text-foreground"
          >
            {checkoutLoading ? "Opening..." : "Get Premium"}
          </Button>
        )}

        <SidebarThemeToggle />
      </div>

      {/* Bottom section */}
      <div className="border-t px-3 py-4 space-y-3">
        {isGuest && guestPromptsRemaining != null && (
          <div className="px-3">
            <Badge
              variant={guestPromptsRemaining > 5 ? "secondary" : guestPromptsRemaining > 0 ? "warning" : "destructive"}
            >
              {guestPromptsRemaining} prompt{guestPromptsRemaining !== 1 ? "s" : ""} left
            </Badge>
          </div>
        )}

        <div className="px-1">
          <StatusBadge />
        </div>

        <div className="px-1">
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

  /* ── Main render ── */
  return (
    <AppShell sidebar={sidebarContent}>
      <div className="relative flex flex-1 flex-col overflow-hidden">
        {/* Error banner */}
        {error && (
          <div className="border-b border-red-200 bg-red-50/90 px-4 py-2 text-sm text-red-700 backdrop-blur-sm dark:border-red-900/70 dark:bg-red-950/40 dark:text-red-300">
            {error}
          </div>
        )}

        {messages.length === 0 ? (
          /* ═══ EMPTY STATE: centered layout ═══ */
          <div className="flex flex-1 flex-col items-center justify-center px-4 pb-8" style={{ animation: "contentRise 0.8s ease-out forwards" }}>
            <div className="w-full max-w-2xl space-y-8 text-center">
              {/* Greeting */}
              <div>
                <h2 className="font-display text-3xl font-bold tracking-tight sm:text-4xl">
                  How are you feeling today?
                </h2>
                <p className="mt-3 text-base text-muted-foreground">
                  Share how you are feeling, and I&apos;ll suggest a grounded next step.
                </p>
              </div>

              {/* Starter prompts */}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {STARTER_PROMPTS.map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => sendMessage(prompt)}
                    className="group rounded-xl border bg-card/60 px-4 py-3.5 text-left text-sm text-foreground backdrop-blur-sm transition-all hover:bg-card hover:shadow-md"
                  >
                    {prompt}
                  </button>
                ))}
              </div>

              {/* Input bar (centered) */}
              <div className="mx-auto w-full max-w-2xl">
                {renderInputBar()}
                {renderInputHint()}
              </div>
            </div>
          </div>
        ) : (
          /* ═══ CHAT STATE: messages + floating bottom input ═══ */
          <>
            {/* Scrollable messages */}
            <div ref={listRef} className="flex-1 overflow-y-auto px-4 py-6" style={{ animation: "contentRise 0.5s ease-out forwards" }}>
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
            </div>

            {/* Guest limit banner */}
            {isGuestLimitReached && (
              <div className="border-t border-amber-200 bg-amber-50/90 px-4 py-3 backdrop-blur-sm dark:border-amber-900/70 dark:bg-amber-950/40">
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

            {/* Floating input at bottom */}
            <div className="px-4 pb-4 pt-2">
              <div className="mx-auto max-w-3xl">
                {renderInputBar()}
                {renderInputHint()}
              </div>
            </div>
          </>
        )}
      </div>

      {/* Therapist search modal */}
      <Dialog open={therapistModalOpen} onOpenChange={setTherapistModalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Find a therapist</DialogTitle>
            <DialogDescription>Search local providers by city or postcode.</DialogDescription>
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
              <div className="rounded-lg border border-red-200 bg-red-50 p-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
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
                <p className="text-xs font-medium text-muted-foreground">Results</p>
                <ul className="space-y-2 text-sm">
                  {therapistResults.map((therapist) => {
                    const link = therapist.source_url || therapist.url;
                    return (
                      <li key={`${therapist.name}-${therapist.address}`} className="rounded-lg border p-3">
                        {link ? (
                          <a className="font-semibold text-primary underline underline-offset-2" href={link} target="_blank" rel="noreferrer">
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

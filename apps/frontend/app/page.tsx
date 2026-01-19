"use client";

import { useEffect, useRef, useState } from "react";

type ChatResponse = {
  coach_message: string;
  exercise?: {
    type: string;
    steps: string[];
    duration_seconds: number;
  };
  resources?: { title: string; url: string; description?: string }[];
  premium_cta?: { enabled: boolean; message: string };
  therapists?: {
    name: string;
    address: string;
    url: string;
    phone: string;
    distance_km: number;
  }[];
  sources?: { source_id: string; text?: string; snippet?: string }[];
  risk_level?: string;
};

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  exercise?: ChatResponse["exercise"];
  resources?: ChatResponse["resources"];
  therapists?: ChatResponse["therapists"];
  sources?: ChatResponse["sources"];
  premium_cta?: ChatResponse["premium_cta"];
  risk_level?: string;
};

type StatusState = {
  mode: "deterministic" | "llm_rag" | null;
  model: string | null;
  backend: "online" | "offline";
};

export function StatusBadge({ fetcher = fetch }: { fetcher?: typeof fetch }) {
  const [status, setStatus] = useState<StatusState>({
    mode: null,
    model: null,
    backend: "online"
  });

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const res = await fetcher("/api/status", { credentials: "include" });
        if (!res.ok) throw new Error("bad status");
        const data = await res.json();
        if (!cancelled) {
          setStatus({
            mode: (data.agent_mode as StatusState["mode"]) ?? "deterministic",
            model: data.model ?? null,
            backend: "online"
          });
        }
      } catch {
        if (!cancelled) {
          setStatus({ mode: null, model: null, backend: "offline" });
        }
      }
    };

    load();
    const interval = setInterval(load, 10000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [fetcher]);

  if (status.backend === "offline") {
    return (
      <div className="rounded-full bg-coral/15 px-4 py-2 text-xs font-semibold text-coral">
        API: offline
      </div>
    );
  }

  const modeText = status.mode === "llm_rag" ? "LLM+RAG enabled." : "Deterministic safety mode: LLM disabled.";

  return (
    <div className="flex items-center gap-3 text-xs">
      <div
        className={`rounded-full px-3 py-1 text-white ${
          status.mode === "llm_rag" ? "bg-emerald-600" : "bg-slate-600"
        }`}
        title={modeText}
      >
        Mode: {status.mode === "llm_rag" ? "LLM+RAG" : "Deterministic"}
      </div>
      {status.model && (
        <span className="rounded-full border border-ink/10 px-3 py-1 text-ink">Model: {status.model}</span>
      )}
    </div>
  );
}

export default function Home() {
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
          if (typeof window !== "undefined") {
            window.location.assign("/login");
          }
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
  }, []);

  const startCheckout = async () => {
    if (!isAuthenticated) {
      setError("Please sign in to continue.");
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
    } finally {
      setCheckoutLoading(false);
    }
  };

  const handleSend = async () => {
    const trimmed = input.trim();
    if (!trimmed || isSending) return;
    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: trimmed
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
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
      if (message === "Failed to fetch") {
        setError("Failed to reach the API.");
      } else {
        setError(message);
      }
    } finally {
      setIsSending(false);
    }
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
    } catch (err) {
      const message = err instanceof Error ? err.message : "Search failed.";
      setTherapistError(message);
    } finally {
      setTherapistLoading(false);
    }
  };

  if (authStatus === "loading") {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center bg-slate-50 text-ink">
        <div className="rounded-2xl border border-slate-200 bg-white px-8 py-6 text-center shadow-sm">
          <h1 className="font-display text-2xl">Mental Health Skills Coach</h1>
          <p className="mt-2 text-sm text-ink/70">Checking session…</p>
        </div>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen flex-col bg-slate-50 text-ink">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-4">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-ink/60">Mental Health Skills Coach</p>
          <h1 className="font-display text-2xl text-ink">Steadying routines, one chat at a time</h1>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge />
          <button
            className="rounded-full bg-coral px-4 py-2 text-xs font-semibold text-white shadow disabled:opacity-60"
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
            {premiumStatus === "premium" ? "Find a therapist" : "Get Premium to find a therapist"}
          </button>
          {premiumStatus === "premium" ? (
            <button
              className="rounded-full border border-emerald-200 bg-emerald-50 px-4 py-2 text-xs font-semibold text-emerald-700"
              disabled
            >
              Premium Active
            </button>
          ) : (
            <button
              className="rounded-full bg-ink px-4 py-2 text-xs font-semibold text-white shadow disabled:opacity-60"
              onClick={startCheckout}
              disabled={checkoutLoading || premiumStatus === "unknown"}
            >
              {checkoutLoading ? "Opening..." : premiumStatus === "unknown" ? "Checking..." : "Get Premium"}
            </button>
          )}
        </div>
      </header>

      {error && (
        <div className="mx-4 mt-4 rounded-xl border border-coral/40 bg-coral/10 p-3 text-sm text-ink">
          {error}
        </div>
      )}

      <div className="flex flex-1 flex-col px-4 py-4">
        <div
          ref={listRef}
          className="flex-1 overflow-y-auto rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
        >
          {messages.length === 0 && (
            <div className="flex h-full items-center justify-center text-sm text-ink/60">
              Share how you are feeling, and I will suggest a grounded next step.
            </div>
          )}
          <div className="space-y-4">
            {messages.map((msg) => (
              <ChatBubble key={msg.id} message={msg} />
            ))}
            {isSending && <div className="flex justify-start text-sm text-ink/60">Thinking...</div>}
          </div>
        </div>

        {therapistModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-4">
            <div className="w-full max-w-lg space-y-4 rounded-2xl bg-white p-5 shadow-xl">
              <div className="flex items-center justify-between">
                <h2 className="font-display text-lg text-ink">Therapist search</h2>
                <button
                  className="text-sm text-ink/60"
                  onClick={() => setTherapistModalOpen(false)}
                >
                  Close
                </button>
              </div>
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-[0.15em] text-ink/60">
                  City or postcode
                </label>
                <input
                  value={therapistLocation}
                  onChange={(e) => setTherapistLocation(e.target.value)}
                  className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
                  placeholder="Stockholm"
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-[0.15em] text-ink/60">
                  Radius (km, optional)
                </label>
                <input
                  value={therapistRadius}
                  onChange={(e) => setTherapistRadius(e.target.value)}
                  className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
                  placeholder="10"
                />
              </div>
              {therapistError && (
                <div className="rounded-xl border border-coral/40 bg-coral/10 p-2 text-sm text-ink">
                  {therapistError}
                </div>
              )}
              <div className="flex flex-col items-end gap-2">
                {premiumStatus === "premium" ? (
                  <button
                    className="rounded-full bg-ink px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
                    onClick={handleTherapistSearch}
                    disabled={therapistLoading}
                  >
                    {therapistLoading ? "Searching..." : "Search"}
                  </button>
                ) : (
                  <button
                    className="rounded-full bg-ink px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
                    onClick={startCheckout}
                    disabled={checkoutLoading}
                  >
                    {checkoutLoading ? "Opening..." : "Get Premium"}
                  </button>
                )}
                {premiumStatus !== "premium" && (
                  <p className="text-xs text-ink/60">Premium is required to search therapists.</p>
                )}
              </div>
              {therapistResults && therapistResults.length > 0 && (
                <div className="space-y-2">
                  <p className="text-xs font-semibold uppercase tracking-[0.15em] text-ink/60">Results</p>
                  <ul className="space-y-2 text-sm">
                    {therapistResults.map((therapist) => (
                      <li key={`${therapist.name}-${therapist.address}`} className="rounded-xl border border-slate-200 p-3">
                        <a className="font-semibold underline" href={therapist.url} target="_blank" rel="noreferrer">
                          {therapist.name}
                        </a>
                        <p className="text-ink/70">{therapist.address}</p>
                        <p className="text-ink/70">Distance: {therapist.distance_km} km</p>
                        <p className="text-ink/70">Phone: {therapist.phone}</p>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        )}

        <div className="mt-4 rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            rows={3}
            className="w-full resize-none rounded-xl border border-slate-200 p-3 text-sm text-ink outline-none focus:ring-2 focus:ring-coral/60"
            placeholder="I feel anxious right now..."
          />
          <div className="mt-2 flex items-center justify-between">
            <span className="text-xs text-ink/50">Enter to send, Shift+Enter for newline</span>
            <button
              onClick={handleSend}
              disabled={isSending || !input.trim()}
              className="rounded-full bg-ink px-4 py-2 text-sm font-semibold text-white shadow hover:bg-ink/90 disabled:opacity-50"
            >
              {isSending ? "Thinking..." : "Send"}
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}

function ChatBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] space-y-3 rounded-2xl px-4 py-3 text-sm shadow ${
          isUser ? "bg-ink text-white" : "bg-slate-100 text-ink"
        }`}
      >
        <p className="whitespace-pre-wrap">{message.content}</p>

        {message.exercise && (
          <div className="space-y-1">
            <p className="text-xs font-semibold uppercase tracking-[0.15em] text-ink/60">
              {message.exercise.type} - {message.exercise.duration_seconds}s
            </p>
            <ul className={`list-disc pl-4 ${isUser ? "text-white/80" : "text-ink/80"}`}>
              {message.exercise.steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ul>
          </div>
        )}

        {message.resources && message.resources.length > 0 && (
          <div className="space-y-1">
            <p className="text-xs font-semibold uppercase tracking-[0.15em] text-ink/60">Resources</p>
            <ul className="space-y-1">
              {message.resources.map((r) => (
                <li key={r.url}>
                  <a className="underline underline-offset-4" href={r.url} target="_blank" rel="noreferrer">
                    {r.title}
                  </a>
                  {r.description && <p className="text-xs opacity-80">{r.description}</p>}
                </li>
              ))}
            </ul>
          </div>
        )}

        {message.therapists && message.therapists.length > 0 && (
          <div className="space-y-1">
            <p className="text-xs font-semibold uppercase tracking-[0.15em] text-ink/60">Therapists</p>
            <ul className="space-y-2 text-sm">
              {message.therapists.map((t) => (
                <li key={`${t.name}-${t.address}`} className="rounded-lg border border-slate-200 p-2">
                  <a className="font-semibold underline" href={t.url} target="_blank" rel="noreferrer">
                    {t.name}
                  </a>
                  <p className="text-ink/70">{t.address}</p>
                  <p className="text-ink/70">Distance: {t.distance_km} km</p>
                  <p className="text-ink/70">Phone: {t.phone}</p>
                </li>
              ))}
            </ul>
          </div>
        )}

        {message.sources && message.sources.length > 0 && (
          <details className="rounded-lg border border-slate-200 bg-white/80 p-2 text-ink">
            <summary className="cursor-pointer text-xs font-semibold">Sources</summary>
            <ul className="space-y-1 pt-2 text-xs">
              {message.sources.map((s, idx) => (
                <li key={`${s.source_id}-${idx}`}>
                  <p className="font-semibold">{s.source_id}</p>
                  <p className="whitespace-pre-wrap text-ink/70">{s.snippet || s.text || "Excerpt unavailable."}</p>
                </li>
              ))}
            </ul>
          </details>
        )}

        {message.premium_cta?.enabled && (
          <div className="rounded-lg border border-coral/40 bg-coral/10 p-2 text-ink">
            <p className="text-xs font-semibold uppercase tracking-[0.15em]">Premium</p>
            <p>{message.premium_cta.message}</p>
          </div>
        )}
      </div>
    </div>
  );
}

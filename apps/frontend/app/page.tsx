"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type ChatResponse = {
  coach_message: string;
  exercise?: {
    type: string;
    steps: string[];
    duration_seconds: number;
  };
  resources?: { title: string; url: string; description?: string }[];
  premium_cta?: { enabled: boolean; message: string };
  sources?: { source_id: string; text?: string; snippet?: string }[];
  risk_level?: string;
};

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  exercise?: ChatResponse["exercise"];
  resources?: ChatResponse["resources"];
  sources?: ChatResponse["sources"];
  premium_cta?: ChatResponse["premium_cta"];
  risk_level?: string;
};

type StatusState = {
  mode: "deterministic" | "llm_rag" | null;
  model: string | null;
  backend: "online" | "offline";
};

const defaultApiBase =
  typeof window === "undefined"
    ? "http://backend:8000"
    : window.location.hostname === "localhost"
      ? "http://localhost:8000"
      : "http://backend:8000";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || defaultApiBase;

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
        const res = await fetcher(`${API_BASE}/status`);
        if (!res.ok) throw new Error("bad status");
        const data = await res.json();
        if (!cancelled) {
          setStatus({
            mode: (data.agent_mode as StatusState["mode"]) ?? "deterministic",
            model: data.model ?? "unknown",
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
        Backend: offline
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
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, isSending]);

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
      const res = await fetch(`${API_BASE}/chat`, {
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
        sources: data.sources,
        premium_cta: data.premium_cta,
        risk_level: data.risk_level
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setIsSending(false);
    }
  };

  const authError =
    typeof window !== "undefined"
      ? new URLSearchParams(window.location.search).get("auth_error")
      : null;

  const crisisCTA = useMemo(() => {
    const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
    if (!lastAssistant) return false;
    return lastAssistant.risk_level === "crisis" || lastAssistant.premium_cta?.enabled;
  }, [messages]);

  return (
    <main className="flex min-h-screen flex-col bg-slate-50 text-ink">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-4">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-ink/60">Mental Health Skills Coach</p>
          <h1 className="font-display text-2xl text-ink">Steadying routines, one chat at a time</h1>
        </div>
        <StatusBadge />
      </header>

      {authError && (
        <div className="mx-4 mt-4 rounded-xl border border-coral/40 bg-coral/10 p-3 text-sm text-ink">
          Google sign-in was canceled or failed. Please try again.
        </div>
      )}

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

        {crisisCTA && (
          <div className="mt-4">
            <button
              className="w-full rounded-xl bg-coral px-4 py-3 text-sm font-semibold text-white shadow hover:bg-coral/90"
              onClick={() => {
                window.location.href = "/premium";
              }}
            >
              Find me a therapist (Premium)
            </button>
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

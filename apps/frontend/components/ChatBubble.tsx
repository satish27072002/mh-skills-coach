"use client";

import type { Message } from "./chat-types";

export default function ChatBubble({ message }: { message: Message }) {
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

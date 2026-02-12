"use client";

import type { Message } from "./chat-types";

type BookingAction = "YES" | "NO";

function formatExpiry(expiresAt: string): string {
  const parsed = new Date(expiresAt);
  if (Number.isNaN(parsed.getTime())) {
    return expiresAt;
  }
  return parsed.toLocaleString();
}

export default function ChatBubble({
  message,
  onBookingAction,
  bookingActionDisabled = false
}: {
  message: Message;
  onBookingAction?: (action: BookingAction) => void;
  bookingActionDisabled?: boolean;
}) {
  const isUser = message.role === "user";
  const showBookingCard = Boolean(
    !isUser && message.requires_confirmation && message.booking_proposal
  );
  const bookingProposal = message.booking_proposal;

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

        {showBookingCard && bookingProposal && (
          <div className="space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-ink">
            <p className="text-xs font-semibold uppercase tracking-[0.15em] text-amber-900">
              Booking proposal
            </p>
            <p>
              <span className="font-semibold">Therapist email:</span> {bookingProposal.therapist_email}
            </p>
            <p>
              <span className="font-semibold">Requested time:</span> {bookingProposal.requested_time}
            </p>
            <p>
              <span className="font-semibold">Subject:</span> {bookingProposal.subject}
            </p>
            <p className="whitespace-pre-wrap">
              <span className="font-semibold">Body:</span> {bookingProposal.body}
            </p>
            <p className="text-xs text-ink/70">
              Expires at: {formatExpiry(bookingProposal.expires_at)}
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="rounded-full bg-ink px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
                onClick={() => onBookingAction?.("YES")}
                disabled={bookingActionDisabled}
              >
                Send email
              </button>
              <button
                type="button"
                className="rounded-full border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-ink disabled:opacity-50"
                onClick={() => onBookingAction?.("NO")}
                disabled={bookingActionDisabled}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

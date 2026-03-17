"use client";

import { AlertTriangle, ExternalLink, Mail, Phone } from "lucide-react";

import type { Message } from "./chat-types";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Separator } from "./ui/separator";

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
  const showBookingCard = Boolean(!isUser && message.requires_confirmation && message.booking_proposal);
  const bookingProposal = message.booking_proposal;
  const isCrisis = !isUser && message.risk_level === "crisis";

  /* ── User bubble ── */
  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-user-bubble px-4 py-2.5 text-sm text-user-bubble-text shadow-sm sm:max-w-[70%]">
          <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>
        </div>
      </div>
    );
  }

  /* ── Assistant bubble ── */
  return (
    <div className="flex justify-start">
      <div
        className={`max-w-[85%] space-y-3 rounded-2xl rounded-bl-md px-4 py-3 text-sm shadow-sm sm:max-w-[70%] ${
          isCrisis
            ? "border border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-950/30"
            : "border bg-card"
        }`}
      >
        {isCrisis ? (
          <div className="flex items-center gap-2 text-xs font-semibold text-danger">
            <AlertTriangle className="h-3.5 w-3.5" />
            Crisis support
          </div>
        ) : null}

        <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>

        {/* Exercise card */}
        {message.exercise ? (
          <div className="mt-2 rounded-lg bg-background/60 p-3 space-y-1.5">
            <p className="text-xs font-semibold text-primary">
              {message.exercise.type}
              {message.exercise.duration_seconds ? ` \u00b7 ${Math.round(message.exercise.duration_seconds / 60)} min` : ""}
            </p>
            <ol className="list-decimal space-y-1 pl-4 text-muted-foreground text-xs">
              {message.exercise.steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          </div>
        ) : null}

        {/* Resources */}
        {message.resources && message.resources.length > 0 ? (
          <div className="space-y-1.5">
            <p className="text-xs font-semibold text-muted-foreground">Resources</p>
            <ul className="space-y-1">
              {message.resources.map((resource) => (
                <li key={resource.url}>
                  <a className="inline-flex items-center gap-1 text-sm font-medium text-accent underline underline-offset-2" href={resource.url} target="_blank" rel="noreferrer">
                    {resource.title}
                    <ExternalLink className="h-3 w-3" />
                  </a>
                  {resource.description ? <p className="text-xs text-muted-foreground">{resource.description}</p> : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {/* Therapists */}
        {message.therapists && message.therapists.length > 0 ? (
          <div className="space-y-2">
            <p className="text-xs font-semibold text-muted-foreground">Nearby therapists</p>
            <ul className="space-y-2 text-sm">
              {message.therapists.map((therapist) => {
                const link = therapist.source_url || therapist.url;
                return (
                  <li key={`${therapist.name}-${therapist.address}`} className="rounded-lg border bg-background/50 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="font-semibold">{therapist.name}</p>
                      <Badge variant="outline">{therapist.distance_km} km</Badge>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">{therapist.address}</p>
                    <div className="mt-2 flex flex-wrap gap-3 text-xs text-muted-foreground">
                      {therapist.phone ? (
                        <span className="inline-flex items-center gap-1"><Phone className="h-3 w-3" />{therapist.phone}</span>
                      ) : null}
                      {therapist.email ? (
                        <span className="inline-flex items-center gap-1"><Mail className="h-3 w-3" />{therapist.email}</span>
                      ) : null}
                      {link ? (
                        <a className="inline-flex items-center gap-1 font-medium text-accent underline underline-offset-2" href={link} target="_blank" rel="noreferrer">
                          View <ExternalLink className="h-3 w-3" />
                        </a>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}

        {/* Sources */}
        {message.sources && message.sources.length > 0 ? (
          <details className="rounded-lg border bg-background/50 p-2">
            <summary className="cursor-pointer text-xs font-semibold text-muted-foreground">Sources</summary>
            <ul className="space-y-2 pt-2 text-xs">
              {message.sources.map((source, idx) => (
                <li key={`${source.source_id}-${idx}`}>
                  <p className="font-semibold">{source.source_id}</p>
                  <p className="whitespace-pre-wrap text-muted-foreground">{source.snippet || source.text || "Excerpt unavailable."}</p>
                </li>
              ))}
            </ul>
          </details>
        ) : null}

        {/* Premium CTA */}
        {message.premium_cta?.enabled ? (
          <div className="rounded-lg border border-warning/30 bg-warning/5 p-3">
            <p className="text-xs font-semibold text-warning">Premium</p>
            <p className="mt-1 text-sm">{message.premium_cta.message}</p>
          </div>
        ) : null}

        {/* Booking proposal */}
        {showBookingCard && bookingProposal ? (
          <div className="rounded-lg border border-accent/30 bg-accent/5 p-3 space-y-2">
            <p className="text-xs font-semibold text-accent">Booking proposal</p>
            <div className="space-y-1 text-sm">
              <p><span className="font-medium">To:</span> {bookingProposal.therapist_email}</p>
              <p><span className="font-medium">Time:</span> {bookingProposal.requested_time}</p>
              <p><span className="font-medium">Subject:</span> {bookingProposal.subject}</p>
              <p className="whitespace-pre-wrap text-muted-foreground">{bookingProposal.body}</p>
            </div>
            <Separator />
            <p className="text-xs text-muted-foreground">Expires: {formatExpiry(bookingProposal.expires_at)}</p>
            <div className="flex gap-2 pt-1">
              <Button type="button" size="sm" onClick={() => onBookingAction?.("YES")} disabled={bookingActionDisabled}>
                Send email
              </Button>
              <Button type="button" variant="outline" size="sm" onClick={() => onBookingAction?.("NO")} disabled={bookingActionDisabled}>
                Cancel
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

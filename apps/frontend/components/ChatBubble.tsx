"use client";

import { AlertTriangle, ExternalLink, Mail, Phone } from "lucide-react";

import type { Message } from "./chat-types";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

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
  bookingActionDisabled = false,
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
        className={`max-w-[92%] space-y-3 rounded-2xl border px-4 py-3 text-sm shadow-sm sm:max-w-[80%] ${
          isUser
            ? "border-primary bg-primary text-[color:var(--background)]"
            : isCrisis
              ? "border-red-300 bg-red-50 text-foreground dark:border-red-900 dark:bg-red-950/30"
              : "bg-surface text-foreground"
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
                  <li key={`${therapist.name}-${therapist.address}`} className="rounded-lg border bg-card p-3 text-foreground">
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
          <details className="rounded-lg border bg-card p-2 text-foreground">
            <summary className="cursor-pointer text-xs font-semibold">Sources</summary>
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
          <Card className="border-amber-300 bg-amber-50 text-foreground dark:bg-amber-950/20">
            <CardHeader>
              <CardTitle className="text-sm uppercase tracking-[0.15em] text-amber-900 dark:text-amber-200">Booking proposal</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
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
              <p className="text-xs text-muted-foreground">Expires at: {formatExpiry(bookingProposal.expires_at)}</p>
              <div className="flex flex-wrap gap-2 pt-1">
                <Button type="button" size="sm" onClick={() => onBookingAction?.("YES")} disabled={bookingActionDisabled}>
                  Send email
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => onBookingAction?.("NO")}
                  disabled={bookingActionDisabled}
                >
                  Cancel
                </Button>
              </div>
            </CardContent>
          </Card>
        ) : null}
      </div>
    </div>
  );
}

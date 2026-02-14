"use client";

import { AlertTriangle, ExternalLink, Mail, Phone } from "lucide-react";

import type { Message } from "./chat-types";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
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

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[92%] space-y-3 rounded-xl border px-4 py-3 text-sm shadow-sm sm:max-w-[80%] ${
          isUser
            ? "border-primary bg-primary text-white"
            : isCrisis
              ? "border-red-300 bg-red-50 text-foreground dark:border-red-900 dark:bg-red-950/30"
              : "bg-surface text-foreground"
        }`}
      >
        {isCrisis ? (
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.15em] text-red-700 dark:text-red-300">
            <AlertTriangle className="h-3.5 w-3.5" />
            Crisis support
          </div>
        ) : null}

        <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>

        {message.exercise ? (
          <div className="space-y-1">
            <p className="text-xs font-semibold uppercase tracking-[0.15em] opacity-70">
              {message.exercise.type} - {message.exercise.duration_seconds}s
            </p>
            <ul className={`list-disc space-y-1 pl-4 ${isUser ? "text-white/80" : "text-foreground/80"}`}>
              {message.exercise.steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {message.resources && message.resources.length > 0 ? (
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-[0.15em] opacity-70">Resources</p>
            <ul className="space-y-2">
              {message.resources.map((resource) => (
                <li key={resource.url}>
                  <a className="inline-flex items-center gap-1 text-sm font-semibold underline" href={resource.url} target="_blank" rel="noreferrer">
                    {resource.title}
                    <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                  {resource.description ? <p className="text-xs opacity-80">{resource.description}</p> : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {message.therapists && message.therapists.length > 0 ? (
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-[0.15em] opacity-70">Therapists</p>
            <ul className="space-y-2 text-sm">
              {message.therapists.map((therapist) => {
                const link = therapist.source_url || therapist.url;
                return (
                  <li key={`${therapist.name}-${therapist.address}`} className="rounded-lg border bg-white/80 p-3 text-foreground dark:bg-slate-900/60">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="font-semibold">{therapist.name}</p>
                      <Badge variant="outline">{therapist.distance_km} km</Badge>
                    </div>
                    <p className="mt-1 text-foreground/70">{therapist.address}</p>
                    <div className="mt-2 flex flex-wrap gap-3 text-xs text-foreground/80">
                      {therapist.phone ? (
                        <span className="inline-flex items-center gap-1">
                          <Phone className="h-3.5 w-3.5" />
                          {therapist.phone}
                        </span>
                      ) : null}
                      {therapist.email ? (
                        <span className="inline-flex items-center gap-1">
                          <Mail className="h-3.5 w-3.5" />
                          {therapist.email}
                        </span>
                      ) : null}
                      {link ? (
                        <a className="inline-flex items-center gap-1 font-semibold underline" href={link} target="_blank" rel="noreferrer">
                          View source
                          <ExternalLink className="h-3.5 w-3.5" />
                        </a>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}

        {message.sources && message.sources.length > 0 ? (
          <details className="rounded-lg border bg-white/70 p-2 text-foreground dark:bg-slate-900/70">
            <summary className="cursor-pointer text-xs font-semibold">Sources</summary>
            <ul className="space-y-2 pt-2 text-xs">
              {message.sources.map((source, idx) => (
                <li key={`${source.source_id}-${idx}`}>
                  <p className="font-semibold">{source.source_id}</p>
                  <p className="whitespace-pre-wrap text-foreground/70">{source.snippet || source.text || "Excerpt unavailable."}</p>
                </li>
              ))}
            </ul>
          </details>
        ) : null}

        {message.premium_cta?.enabled ? (
          <Card className="border-amber-300/70 bg-amber-50 dark:bg-amber-950/20">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Premium</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-foreground/90">{message.premium_cta.message}</p>
            </CardContent>
          </Card>
        ) : null}

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
              <Separator />
              <p className="text-xs text-foreground/70">Expires at: {formatExpiry(bookingProposal.expires_at)}</p>
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

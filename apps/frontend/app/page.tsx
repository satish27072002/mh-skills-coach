"use client";

import { useState } from "react";

type ChatResponse = {
  coach_message: string;
  exercise?: {
    type: string;
    steps: string[];
    duration_seconds: number;
  };
  resources?: { title: string; url: string }[];
  premium_cta?: { enabled: boolean; message: string };
};

export default function Home() {
  const [message, setMessage] = useState("");
  const [response, setResponse] = useState<ChatResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const apiBase = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!message.trim()) {
      return;
    }
    setIsLoading(true);
    try {
      const res = await fetch(`${apiBase}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message })
      });
      const data = (await res.json()) as ChatResponse;
      setResponse(data);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <main className="min-h-screen px-6 py-10">
      <div className="mx-auto max-w-3xl space-y-8">
        <header className="space-y-3">
          <p className="text-sm uppercase tracking-[0.3em] text-ink/60">
            Mental Health Skills Coach
          </p>
          <h1 className="font-display text-4xl text-ink md:text-5xl">
            A calm place to practice steadying routines
          </h1>
          <p className="text-lg text-ink/70">
            This demo suggests grounded coping exercises and gentle next steps.
          </p>
        </header>

        <section className="rounded-3xl border border-ink/10 bg-white/70 p-6 shadow-xl backdrop-blur">
          <form onSubmit={handleSubmit} className="space-y-4">
            <label className="block text-sm font-display uppercase tracking-[0.2em] text-ink/60">
              Share what you are feeling
            </label>
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              rows={3}
              className="w-full rounded-2xl border border-ink/15 bg-white/90 p-4 text-base text-ink shadow-inner focus:outline-none focus:ring-2 focus:ring-coral"
              placeholder="I feel anxious right now"
            />
            <button
              type="submit"
              disabled={isLoading}
              className="rounded-full bg-ink px-6 py-3 font-display text-sm uppercase tracking-[0.2em] text-fog transition hover:translate-y-[-1px] hover:bg-ink/90 disabled:opacity-60"
            >
              {isLoading ? "Thinking..." : "Coach me"}
            </button>
          </form>
        </section>

        {response && (
          <section className="space-y-4 rounded-3xl border border-ink/10 bg-white/80 p-6 shadow-lg">
            <p className="text-lg text-ink">{response.coach_message}</p>
            {response.exercise && (
              <div className="space-y-2 rounded-2xl border border-tide/40 bg-tide/10 p-4">
                <p className="font-display text-sm uppercase tracking-[0.2em] text-ink/60">
                  {response.exercise.type} ? {response.exercise.duration_seconds}s
                </p>
                <ul className="list-disc pl-5 text-ink/80">
                  {response.exercise.steps.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ul>
              </div>
            )}
            {response.resources && (
              <div className="space-y-2">
                <p className="font-display text-sm uppercase tracking-[0.2em] text-ink/60">
                  Helpful resources
                </p>
                <ul className="space-y-2">
                  {response.resources.map((resource) => (
                    <li key={resource.url}>
                      <a
                        className="text-coral underline-offset-4 hover:underline"
                        href={resource.url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {resource.title}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {response.premium_cta?.enabled && (
              <div className="rounded-2xl border border-coral/40 bg-coral/10 p-4 text-ink">
                <p className="font-display text-sm uppercase tracking-[0.2em]">
                  Premium
                </p>
                <p>{response.premium_cta.message}</p>
              </div>
            )}
          </section>
        )}
      </div>
    </main>
  );
}

"use client";

import { useEffect, useState } from "react";

type StatusState = {
  mode: "deterministic" | "llm_rag" | null;
  model: string | null;
  backend: "online" | "offline";
};

export default function StatusBadge({ fetcher = fetch }: { fetcher?: typeof fetch }) {
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

"use client";

import { useEffect, useState } from "react";
import { Badge } from "./ui/badge";

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
      <div className="rounded-full bg-red-100 px-4 py-2 text-xs font-semibold text-red-700 dark:bg-red-950/40 dark:text-red-300">
        API: offline
      </div>
    );
  }

  const modeText = status.mode === "llm_rag" ? "LLM+RAG enabled." : "Deterministic safety mode: LLM disabled.";

  return (
    <div className="flex items-center gap-3 text-xs">
      <Badge variant={status.mode === "llm_rag" ? "success" : "secondary"} title={modeText}>
        Mode: {status.mode === "llm_rag" ? "LLM+RAG" : "Deterministic"}
      </Badge>
      {status.model && (
        <span className="rounded-full border px-3 py-1 text-foreground">Model: {status.model}</span>
      )}
    </div>
  );
}

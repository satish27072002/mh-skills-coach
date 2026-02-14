import type { ReactNode } from "react";

import { Separator } from "./ui/separator";

export default function AppShell({
  title,
  subtitle,
  actions,
  children
}: {
  title: string;
  subtitle: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="mx-auto flex min-h-screen w-full max-w-7xl flex-col px-3 py-3 sm:px-6 sm:py-5">
      <header className="rounded-xl border bg-surface/90 px-4 py-4 shadow-sm backdrop-blur sm:px-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-muted">Mental Health Skills Coach</p>
            <h1 className="font-display text-2xl leading-tight sm:text-3xl">{title}</h1>
            <p className="max-w-2xl text-sm text-muted">{subtitle}</p>
          </div>
          {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
        </div>
      </header>

      <main className="mt-4 flex flex-1 flex-col">{children}</main>

      <Separator className="mt-4" />
      <footer className="py-4 text-xs text-muted">
        This product is not medical advice. If you are in immediate danger, contact local emergency services.
      </footer>
    </div>
  );
}

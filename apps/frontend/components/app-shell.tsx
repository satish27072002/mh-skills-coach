import type { ReactNode } from "react";

export default function AppShell({
  title,
  subtitle,
  actions,
  children
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b bg-card/80 backdrop-blur-lg">
        <div className="mx-auto flex h-14 max-w-3xl items-center justify-between px-4">
          <span className="text-sm font-semibold text-primary">MH Skills Coach</span>
          {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
        </div>
      </header>

      <main className="flex flex-1 flex-col">{children}</main>

      <footer className="border-t py-3 text-center text-xs text-muted-foreground">
        Not medical advice. If you are in immediate danger, contact local emergency services.
      </footer>
    </div>
  );
}

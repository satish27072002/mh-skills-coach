"use client";

import { Menu, PanelLeftClose } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";

import { Button } from "./ui/button";

export default function AppShell({
  sidebar,
  children,
}: {
  sidebar?: ReactNode;
  children: ReactNode;
}) {
  const [sidebarOpen, setSidebarOpen] = useState(true);

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Mobile overlay backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={[
          /* Base styling */
          "flex flex-col border-r bg-sidebar backdrop-blur-md transition-all duration-300 ease-out overflow-hidden",
          /* Mobile: fixed overlay */
          "fixed inset-y-0 left-0 z-50 w-64",
          sidebarOpen ? "translate-x-0" : "-translate-x-full",
          /* Desktop: static flex member, width collapse */
          "md:static md:z-auto md:translate-x-0",
          sidebarOpen ? "md:w-64 md:min-w-[16rem]" : "md:w-0 md:min-w-0 md:border-r-0",
        ].join(" ")}
      >
        {/* Inner wrapper keeps content at full width during collapse animation */}
        <div className="flex w-64 min-w-[16rem] flex-1 flex-col">
          {/* Close button row */}
          <div className="flex items-center justify-end px-3 py-2">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setSidebarOpen(false)}
              aria-label="Close sidebar"
              className="h-8 w-8 text-foreground/60 hover:text-foreground"
            >
              <PanelLeftClose className="h-4 w-4" />
            </Button>
          </div>

          {sidebar}
        </div>
      </aside>

      {/* Main content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Header bar — visible when sidebar is closed */}
        {!sidebarOpen && (
          <header className="flex items-center gap-3 border-b px-4 py-2.5 backdrop-blur-md">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setSidebarOpen(true)}
              aria-label="Open sidebar"
              className="h-8 w-8 text-foreground/60 hover:text-foreground"
            >
              <Menu className="h-5 w-5" />
            </Button>
            <span className="font-display text-sm font-semibold">
              Mental Health Skills Coach
            </span>
          </header>
        )}

        <main className="flex flex-1 flex-col overflow-hidden">{children}</main>
      </div>
    </div>
  );
}

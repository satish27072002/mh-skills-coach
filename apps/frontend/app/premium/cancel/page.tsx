"use client";

import AppShell from "../../../components/app-shell";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";

export default function PremiumCancelPage() {
  return (
    <AppShell>
      <div className="mx-auto mt-8 w-full max-w-xl px-4">
        <Card>
          <CardHeader>
            <CardTitle>Checkout canceled</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p>Your payment was canceled. No charge was made. You can upgrade any time.</p>
            <a
              className="inline-flex h-10 items-center justify-center bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary/90"
              href="/"
            >
              Back to chat
            </a>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}

"use client";

import Link from "next/link";
import AppShell from "../../../components/app-shell";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";

export default function PremiumCancelPage() {
  return (
    <AppShell>
      <div className="flex flex-1 items-center justify-center px-4">
        <Card className="w-full max-w-xl">
          <CardHeader>
            <CardTitle>Checkout canceled</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-muted-foreground">
              Your payment was canceled. No charge was made. You can upgrade any time.
            </p>
            <Link
              href="/"
              className="inline-flex h-10 items-center justify-center rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary/90"
            >
              Back to chat
            </Link>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}

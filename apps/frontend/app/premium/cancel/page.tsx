"use client";

export default function PremiumCancelPage() {
  return (
    <main className="min-h-screen bg-slate-50 px-6 py-16 text-ink">
      <div className="mx-auto max-w-xl space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="font-display text-2xl">Checkout canceled</h1>
        <p>Your payment was canceled. You can try again anytime.</p>
        <a className="text-sm font-semibold text-ink underline" href="/">
          Back to chat
        </a>
      </div>
    </main>
  );
}

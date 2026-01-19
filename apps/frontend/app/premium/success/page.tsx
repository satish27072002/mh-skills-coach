export default function PremiumSuccessPage() {
  return (
    <main className="min-h-screen bg-slate-50 px-6 py-16 text-ink">
      <div className="mx-auto max-w-xl space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="font-display text-2xl">Premium Active</h1>
        <p>Your premium access is now active. You can use the therapist directory at any time.</p>
        <a className="text-sm font-semibold text-ink underline" href="/">
          Back to chat
        </a>
      </div>
    </main>
  );
}

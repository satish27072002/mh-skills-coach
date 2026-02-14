import AppShell from "../../../components/app-shell";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";

export default function PremiumSuccessPage() {
  return (
    <AppShell title="Premium active" subtitle="Your therapist discovery features are now unlocked.">
      <div className="mx-auto mt-8 w-full max-w-xl">
        <Card>
          <CardHeader>
            <CardTitle>Premium Active</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p>Your premium access is now active. You can use therapist search at any time.</p>
            <a
              className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary/90 dark:bg-white dark:text-gray-900"
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

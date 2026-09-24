import Link from "next/link";

import { Logo } from "@/components/common/logo";
import { Button } from "@/components/ui/button";
import { PricingPlans } from "@/features/billing/pricing-plans";
import { getServerUser } from "@/lib/auth/server-session";

export const metadata = { title: "Pricing" };

export default async function Pricing() {
  const user = await getServerUser();
  return (
    <div className="min-h-dvh">
      <header className="border-b border-border/60">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4">
          <Link href="/"><Logo /></Link>
          <Button asChild>{user ? <Link href="/chat">Open Nova</Link> : <Link href="/signup">Get started</Link>}</Button>
        </div>
      </header>
      <main className="mx-auto max-w-5xl space-y-8 px-4 py-16">
        <div className="space-y-2 text-center">
          <h1 className="text-3xl font-bold tracking-tight">Simple plans</h1>
          <p className="text-muted-foreground">Start free. Upgrade when you need more.</p>
        </div>
        <PricingPlans signedIn={!!user} currentPlan={user?.plan_key ?? null} />
      </main>
    </div>
  );
}

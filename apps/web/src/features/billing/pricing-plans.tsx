"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

import { usePlans } from "./api";
import { PlanCards } from "./plan-cards";

export function PricingPlans({ signedIn, currentPlan }: { signedIn: boolean; currentPlan: string | null }) {
  const { data, isLoading } = usePlans();
  if (isLoading || !data) return <Skeleton className="h-80 w-full" />;
  return (
    <PlanCards
      plans={data.plans}
      current={currentPlan}
      action={(p) => (
        <Button asChild variant={p.key === "plus" ? "primary" : "outline"}>
          <Link href={signedIn ? (p.price_paise ? "/settings/billing" : "/chat") : "/signup"}>
            {p.price_paise ? `Get ${p.name}` : "Start free"}
          </Link>
        </Button>
      )}
    />
  );
}

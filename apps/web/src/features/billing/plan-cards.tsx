"use client";

import { Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { formatPrice, LIMIT_LABELS, type PlanInfo } from "./api";

export function PlanCards({
  plans,
  current,
  action,
}: {
  plans: PlanInfo[];
  current?: string | null;
  action: (p: PlanInfo) => React.ReactNode;
}) {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {plans.map((p) => (
        <div key={p.key} className={cn("flex flex-col gap-4 rounded-xl border border-border bg-surface-raised p-5", p.key === "plus" && "border-primary/60 ring-1 ring-primary/30")}>
          <div>
            <h3 className="font-semibold">{p.name}</h3>
            <p className="mt-1 text-2xl font-semibold">
              {formatPrice(p.price_paise, p.currency)}
              {p.price_paise ? <span className="text-sm font-normal text-muted-foreground"> / month</span> : null}
            </p>
            {p.description ? <p className="mt-1 text-sm text-muted-foreground">{p.description}</p> : null}
          </div>
          <ul className="flex-1 space-y-2 text-sm">
            {LIMIT_LABELS.map(([k, fmt]) => {
              const label = fmt(p.limits_summary[k] ?? null);
              return label ? (
                <li key={k} className="flex gap-2">
                  <Check className="mt-0.5 size-4 shrink-0 text-primary" />
                  {label}
                </li>
              ) : null;
            })}
          </ul>
          {current === p.key ? <Button variant="outline" disabled>Current plan</Button> : action(p)}
        </div>
      ))}
    </div>
  );
}

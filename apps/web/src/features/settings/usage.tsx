"use client";

import { useQuota } from "@/features/chat/api";
import { cn } from "@/lib/utils";

import { Section } from "./section";

function Meter({ label, used, limit, resets }: { label: string; used: number; limit: number; resets: string }) {
  const pct = limit ? Math.min(100, (used / limit) * 100) : 0;
  return (
    <div className="space-y-1.5 px-5 py-4">
      <div className="flex justify-between text-sm">
        <span className="font-medium">{label}</span>
        <span className="text-muted-foreground">{used.toLocaleString()} / {limit.toLocaleString()}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-accent" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
        <div className={cn("h-full rounded-full bg-primary", pct >= 80 && "bg-warning", pct >= 100 && "bg-destructive")} style={{ width: `${pct}%` }} />
      </div>
      <p className="text-xs text-muted-foreground">Resets {new Date(resets).toLocaleString()}</p>
    </div>
  );
}

export function UsageSettings() {
  const { data } = useQuota();
  if (!data) return null;
  return (
    <Section title="Usage" description={`You're on the ${data.plan_key} plan.`}>
      <Meter label="Messages today" used={data.used.messages_today} limit={Number(data.limits.messages_per_day ?? 0)} resets={data.period_resets.daily_at} />
      <Meter label="Tokens this month" used={data.used.tokens_month} limit={Number(data.limits.monthly_token_quota ?? 0)} resets={data.period_resets.monthly_at} />
    </Section>
  );
}

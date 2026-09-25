"use client";

import { useUsage } from "@/features/chat/api";
import type { GroqLimits } from "@/lib/types";
import { cn } from "@/lib/utils";

import { Row, Section } from "./section";

function when(iso: string | null): string | null {
  if (!iso) return null;
  const secs = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  if (secs <= 0) return "Reset since this was reported";
  if (secs < 60) return `Resets in ${secs}s`;
  if (secs < 3600) return `Resets in ${Math.round(secs / 60)} min`;
  return `Resets ${new Date(iso).toLocaleString()}`;
}

/** Remaining out of the Groq key's allowance; the bar shows what is left. */
function Allowance({ label, limit, remaining, resetsAt }: { label: string; limit: number | null; remaining: number | null; resetsAt: string | null }) {
  if (limit == null || remaining == null) return null;
  const pct = limit ? Math.max(0, Math.min(100, (remaining / limit) * 100)) : 0;
  const reset = when(resetsAt);
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between gap-3 text-sm">
        <span>{label}</span>
        <span className="text-muted-foreground">{remaining.toLocaleString()} left of {limit.toLocaleString()}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-accent" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} aria-label={`${label} left`}>
        <div className={cn("h-full rounded-full bg-primary", pct <= 20 && "bg-warning", pct <= 5 && "bg-destructive")} style={{ width: `${pct}%` }} />
      </div>
      {reset ? <p className="text-xs text-muted-foreground">{reset}</p> : null}
    </div>
  );
}

function ModelLimits({ g }: { g: GroqLimits }) {
  return (
    <div className="space-y-3 px-5 py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium">{g.display_name}</p>
        <p className="text-xs text-muted-foreground">As of {new Date(g.observed_at).toLocaleTimeString()}</p>
      </div>
      <Allowance label="Requests per day" limit={g.requests_limit} remaining={g.requests_remaining} resetsAt={g.requests_reset_at} />
      <Allowance label="Tokens per minute" limit={g.tokens_limit} remaining={g.tokens_remaining} resetsAt={g.tokens_reset_at} />
    </div>
  );
}

export function UsageSettings() {
  const { data, isPending, isError, refetch } = useUsage();
  if (isPending) return <Section title="Usage"><p className="px-5 py-4 text-sm text-muted-foreground">Loading…</p></Section>;
  if (isError || !data) {
    return (
      <Section title="Usage">
        <div className="flex items-center justify-between gap-3 px-5 py-4 text-sm">
          <span className="text-muted-foreground">Couldn&apos;t load your usage.</span>
          <button type="button" onClick={() => void refetch()} className="font-medium underline underline-offset-4">Try again</button>
        </div>
      </Section>
    );
  }
  const t = data.totals;
  return (
    <div className="space-y-6">
      <Section title="Groq API key limits" description="Nova sets no limits of its own. You can use as much as your Groq API key allows; these numbers come from Groq with every reply.">
        {data.groq.length ? (
          data.groq.map((g) => <ModelLimits key={g.groq_model_id} g={g} />)
        ) : (
          <p className="px-5 py-4 text-sm text-muted-foreground">Send a message and your key&apos;s limits will show up here.</p>
        )}
        <p className="px-5 py-3 text-xs text-muted-foreground">
          Groq also has daily token limits that it doesn&apos;t report per reply. See all of them on{" "}
          <a href="https://console.groq.com/settings/limits" target="_blank" rel="noreferrer" className="underline underline-offset-4">Groq&apos;s limits page</a>.
        </p>
      </Section>
      <Section title="Your usage">
        <Row label="Messages today"><span className="text-sm tabular-nums">{t.messages_today.toLocaleString()}</span></Row>
        <Row label="Tokens today"><span className="text-sm tabular-nums">{t.tokens_today.toLocaleString()}</span></Row>
        <Row label="Tokens this month"><span className="text-sm tabular-nums">{t.tokens_month.toLocaleString()}</span></Row>
      </Section>
    </div>
  );
}

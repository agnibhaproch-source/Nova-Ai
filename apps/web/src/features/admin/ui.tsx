"use client";

import { useQuery } from "@tanstack/react-query";

import { ErrorState } from "@/components/common/states";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type Envelope, type ListEnvelope } from "@/lib/api/client";
import { cn } from "@/lib/utils";

export function useAdmin<T>(path: string, opts: { list?: boolean; refetch?: number } = {}) {
  return useQuery({
    queryKey: ["admin", path],
    refetchInterval: opts.refetch,
    queryFn: async () =>
      opts.list ? ((await api<ListEnvelope<unknown>>(`/admin${path}`)).data as T) : (await api<Envelope<T>>(`/admin${path}`)).data,
  });
}

export function Loadable<T>({ q, children }: { q: { data?: T; error: unknown; isLoading: boolean; refetch: () => unknown }; children: (d: T) => React.ReactNode }) {
  if (q.isLoading) return <Skeleton className="h-40 w-full" />;
  if (q.error || q.data === undefined) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  return <>{children(q.data)}</>;
}

export function PageTitle({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
      <h1 className="text-xl font-semibold">{title}</h1>
      {children}
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface-raised p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export function Table({ head, rows, empty = "Nothing here yet." }: { head: string[]; rows: React.ReactNode[][]; empty?: string }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full text-left text-sm">
        <thead className="bg-surface text-xs text-muted-foreground">
          <tr>{head.map((h) => <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.length ? (
            rows.map((r, i) => (
              <tr key={i}>{r.map((c, j) => <td key={j} className="whitespace-nowrap px-3 py-2 align-top">{c}</td>)}</tr>
            ))
          ) : (
            <tr><td colSpan={head.length} className="px-3 py-6 text-center text-muted-foreground">{empty}</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: "ok" | "bad" | "warn" | "neutral"; children: React.ReactNode }) {
  return (
    <span className={cn("rounded px-1.5 py-0.5 text-xs",
      tone === "ok" && "bg-success/15 text-success",
      tone === "bad" && "bg-destructive/15 text-destructive",
      tone === "warn" && "bg-warning/20",
      tone === "neutral" && "bg-accent")}>
      {children}
    </span>
  );
}

/** Minimal dependency-free bar chart. */
export function Bars({ data, label }: { data: { x: string; y: number }[]; label: string }) {
  const max = Math.max(1, ...data.map((d) => d.y));
  return (
    <figure className="rounded-xl border border-border bg-surface-raised p-4">
      <figcaption className="mb-3 text-sm font-medium">{label}</figcaption>
      {data.length ? (
        <div className="flex h-32 items-end gap-1" role="img" aria-label={label}>
          {data.map((d) => (
            <div key={d.x} title={`${d.x}: ${d.y}`} className="min-w-1 flex-1 rounded-t bg-primary/70" style={{ height: `${(d.y / max) * 100}%` }} />
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No data for this range.</p>
      )}
    </figure>
  );
}

export const fmtDate = (v: unknown) => (v ? new Date(String(v)).toLocaleString() : "—");
export const fmtNum = (v: unknown) => (typeof v === "number" ? v.toLocaleString() : "—");

export function askReason(what: string): string | null {
  const r = window.prompt(`Reason for ${what} (recorded in the audit log):`);
  return r && r.trim().length >= 3 ? r.trim() : null;
}

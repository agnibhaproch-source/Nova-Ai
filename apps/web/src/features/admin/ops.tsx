"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";

import { askReason, Badge, Bars, fmtDate, fmtNum, inr, Loadable, PageTitle, Stat, Table, useAdmin } from "./ui";

type R = Record<string, unknown>;
const s = (v: unknown) => (v == null ? "—" : String(v));

function useAct() {
  const qc = useQueryClient();
  return async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      toast.success(ok);
      await qc.invalidateQueries({ queryKey: ["admin"] });
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };
}

export function Dashboard() {
  const [range, setRange] = useState<"24h" | "7d" | "30d">("7d");
  const q = useAdmin<R>(`/dashboard?range=${range}`);
  return (
    <>
      <PageTitle title="Dashboard">
        <div className="flex gap-1">
          {(["24h", "7d", "30d"] as const).map((r) => (
            <Button key={r} size="sm" variant={r === range ? "primary" : "outline"} onClick={() => setRange(r)}>{r}</Button>
          ))}
        </div>
      </PageTitle>
      <Loadable q={q}>
        {(d) => (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat label="Users" value={fmtNum(d.users_total)} hint={`${fmtNum(d.new_users)} new`} />
              <Stat label="Active users" value={fmtNum(d.active_users)} />
              <Stat label="Messages" value={fmtNum(d.messages)} />
              <Stat label="Tokens" value={fmtNum(d.tokens)} hint={d.estimated_cost_usd != null ? `≈ $${s(d.estimated_cost_usd)}` : undefined} />
              <Stat label="Error rate" value={`${((Number(d.error_rate) || 0) * 100).toFixed(1)}%`} />
              <Stat label="Active subscriptions" value={fmtNum(d.active_subscriptions)} />
              <Stat label="MRR" value={inr(Number(d.mrr_paise) || 0)} />
            </div>
            <Bars label="Messages" data={((d.series as R[]) ?? []).map((p) => ({ x: fmtDate(p.t), y: Number(p.messages) }))} />
            <h2 className="pt-2 font-medium">Top users by tokens</h2>
            <Table
              head={["Email", "Plan", "Tokens", "Est. cost"]}
              rows={((d.top_users as R[]) ?? []).map((u) => [s(u.email), s(u.plan_key), fmtNum(u.tokens), `$${s(u.estimated_cost_usd)}`])}
            />
          </div>
        )}
      </Loadable>
    </>
  );
}

export function Health() {
  const q = useAdmin<R>("/health", { refetch: 15_000 });
  return (
    <>
      <PageTitle title="System health" />
      <Loadable q={q}>
        {(d) => (
          <div className="grid gap-3 md:grid-cols-2">
            {Object.entries(d).map(([k, v]) => {
              const val = v as R | number | null;
              const status = typeof val === "object" && val ? s(val.status ?? val.mode ?? "") : "";
              return (
                <div key={k} className="rounded-xl border border-border bg-surface-raised p-4">
                  <div className="flex items-center justify-between">
                    <p className="font-medium capitalize">{k.replace(/_/g, " ")}</p>
                    {status ? <Badge tone={status === "ok" || status === "user" || status === "server" || status === "configured" ? "ok" : status === "down" ? "bad" : "warn"}>{status}</Badge> : null}
                  </div>
                  <pre className="mt-2 overflow-x-auto text-xs text-muted-foreground">{typeof val === "object" ? JSON.stringify(val, null, 2) : s(val)}</pre>
                </div>
              );
            })}
          </div>
        )}
      </Loadable>
    </>
  );
}

export function Errors() {
  const q = useAdmin<Record<string, { code: string; count: number }[]>>("/errors");
  return (
    <>
      <PageTitle title="Errors (last 24 h)" />
      <Loadable q={q}>
        {(d) => (
          <div className="grid gap-4 md:grid-cols-2">
            {Object.entries(d).map(([area, rows]) => (
              <div key={area}>
                <h2 className="mb-2 font-medium capitalize">{area}</h2>
                <Table head={["Code", "Count"]} rows={(rows ?? []).map((r) => [s(r.code), fmtNum(r.count)])} empty="No errors." />
              </div>
            ))}
          </div>
        )}
      </Loadable>
    </>
  );
}

export function Usage() {
  const [group, setGroup] = useState<"day" | "model" | "kind">("day");
  const q = useAdmin<R[]>(`/usage?days=30&group_by=${group}`, { list: true });
  return (
    <>
      <PageTitle title="Usage (30 days)">
        <div className="flex gap-1">
          {(["day", "model", "kind"] as const).map((g) => (
            <Button key={g} size="sm" variant={g === group ? "primary" : "outline"} onClick={() => setGroup(g)}>{g}</Button>
          ))}
        </div>
      </PageTitle>
      <Loadable q={q}>
        {(rows) => (
          <Table
            head={[group, "Requests", "Prompt tokens", "Completion tokens", "Errors", "Est. cost"]}
            rows={rows.map((r) => [group === "day" ? fmtDate(r.key) : s(r.key), fmtNum(r.requests), fmtNum(r.prompt_tokens), fmtNum(r.completion_tokens), fmtNum(r.errors), r.estimated_cost_usd != null ? `$${s(r.estimated_cost_usd)}` : "—"])}
          />
        )}
      </Loadable>
    </>
  );
}

export function Billing() {
  const act = useAct();
  const subs = useAdmin<R[]>("/subscriptions", { list: true });
  const pays = useAdmin<R[]>("/payments", { list: true });
  const hooks = useAdmin<R[]>("/webhook-events", { list: true });
  return (
    <div className="space-y-6">
      <PageTitle title="Billing" />
      <section>
        <h2 className="mb-2 font-medium">Subscriptions</h2>
        <Loadable q={subs}>
          {(rows) => (
            <Table head={["User", "Plan", "Status", "Period end", "Razorpay id"]} rows={rows.map((r) => [s(r.user_id).slice(0, 8), s(r.plan_key), <Badge key="b" tone={r.status === "active" ? "ok" : "neutral"}>{s(r.status)}</Badge>, fmtDate(r.current_period_end), s(r.razorpay_subscription_id)])} />
          )}
        </Loadable>
      </section>
      <section>
        <h2 className="mb-2 font-medium">Payments</h2>
        <Loadable q={pays}>
          {(rows) => <Table head={["User", "Amount", "Status", "Method", "Date"]} rows={rows.map((r) => [s(r.user_id).slice(0, 8), inr(Number(r.amount_paise) || 0), s(r.status), s(r.method), fmtDate(r.created_at)])} />}
        </Loadable>
      </section>
      <section>
        <h2 className="mb-2 font-medium">Webhook events</h2>
        <Loadable q={hooks}>
          {(rows) => (
            <Table
              head={["Event", "Received", "Processed", "Error", ""]}
              rows={rows.map((r) => [
                s(r.event_type),
                fmtDate(r.received_at),
                r.processed_at ? fmtDate(r.processed_at) : <Badge key="p" tone="warn">pending</Badge>,
                s(r.processing_error),
                r.processing_error ? (
                  <Button key="r" size="sm" variant="outline" onClick={() => { const reason = askReason("reprocessing"); if (reason) void act(() => api(`/admin/webhook-events/${s(r.id)}/reprocess`, { method: "POST", json: { reason } }), "Reprocessed"); }}>
                    Reprocess
                  </Button>
                ) : null,
              ])}
            />
          )}
        </Loadable>
      </section>
    </div>
  );
}

export function Moderation() {
  const act = useAct();
  const q = useAdmin<R[]>("/moderation/flags", { list: true });
  const set = (id: string, status: string) =>
    act(() => api(`/admin/moderation/flags/${id}`, { method: "PATCH", json: { status, resolution_note: window.prompt("Note (optional)") || null } }), "Updated");
  return (
    <>
      <PageTitle title="Moderation flags" />
      <Loadable q={q}>
        {(rows) => (
          <Table
            head={["Created", "Source", "Category", "Status", "Details", ""]}
            rows={rows.map((r) => [
              fmtDate(r.created_at),
              s(r.source),
              s(r.category),
              <Badge key="s" tone={r.status === "open" ? "warn" : "neutral"}>{s(r.status)}</Badge>,
              <span key="d" className="block max-w-80 truncate">{typeof r.details === "object" ? JSON.stringify(r.details) : s(r.details)}</span>,
              r.status === "open" || r.status === "reviewing" ? (
                <div key="a" className="flex gap-1">
                  <Button size="sm" variant="outline" onClick={() => void set(s(r.id), "resolved")}>Resolve</Button>
                  <Button size="sm" variant="ghost" onClick={() => void set(s(r.id), "dismissed")}>Dismiss</Button>
                </div>
              ) : null,
            ])}
            empty="No flags."
          />
        )}
      </Loadable>
    </>
  );
}

export function Models() {
  const act = useAct();
  const q = useAdmin<R[]>("/models", { list: true });
  return (
    <>
      <PageTitle title="Models" />
      <Loadable q={q}>
        {(rows) => (
          <Table
            head={["Key", "Groq model", "Context", "Tools", "Plans", "Status", ""]}
            rows={rows.map((m) => [
              s(m.display_name) + ` (${s(m.key)})`,
              <code key="g" className="text-xs">{s(m.groq_model_id) || "not configured"}</code>,
              fmtNum(m.context_window),
              m.supports_tools ? "yes" : "no",
              ((m.plans as string[]) ?? []).join(", "),
              <Badge key="st" tone={m.enabled ? "ok" : "bad"}>{m.enabled ? "enabled" : m.admin_disabled ? "disabled by admin" : "off"}</Badge>,
              m.groq_model_id ? (
                <Button key="t" size="sm" variant="outline" onClick={() => { const reason = askReason(m.enabled ? "disabling" : "enabling"); if (reason) void act(() => api(`/admin/models/${s(m.key)}`, { method: "PATCH", json: { enabled: !m.enabled, reason } }), "Saved"); }}>
                  {m.enabled ? "Disable" : "Enable"}
                </Button>
              ) : null,
            ])}
          />
        )}
      </Loadable>
    </>
  );
}

export function Plans() {
  const act = useAct();
  const q = useAdmin<R[]>("/plans", { list: true });
  const [editing, setEditing] = useState<string | null>(null);
  const [json, setJson] = useState("");
  return (
    <>
      <PageTitle title="Plans" />
      <Loadable q={q}>
        {(rows) => (
          <div className="space-y-3">
            {rows.map((p) => (
              <div key={s(p.key)} className="rounded-xl border border-border bg-surface-raised p-4">
                <div className="flex flex-wrap items-center gap-3">
                  <p className="font-medium">{s(p.name)}</p>
                  <span className="text-sm text-muted-foreground">{inr(Number(p.price_paise) || 0)} / month</span>
                  <Badge tone={p.is_active ? "ok" : "bad"}>{p.is_active ? "active" : "inactive"}</Badge>
                  <span className="text-xs text-muted-foreground">Razorpay plan: {s(p.razorpay_plan_id)}</span>
                  <div className="flex-1" />
                  <Button size="sm" variant="outline" onClick={() => { setEditing(s(p.key)); setJson(JSON.stringify(p.limits, null, 2)); }}>Edit limits</Button>
                </div>
                {editing === p.key ? (
                  <div className="mt-3 space-y-2">
                    <textarea value={json} onChange={(e) => setJson(e.target.value)} rows={12} className="w-full rounded-md border border-border bg-surface p-2 font-mono text-xs" aria-label="Plan limits JSON" />
                    <div className="flex gap-2">
                      <Button size="sm" onClick={() => {
                        let limits: unknown;
                        try { limits = JSON.parse(json); } catch { return toast.error("Limits must be valid JSON"); }
                        const reason = askReason("changing plan limits");
                        if (reason) void act(() => api(`/admin/plans/${s(p.key)}`, { method: "PATCH", json: { limits, reason } }), "Plan updated").then(() => setEditing(null));
                      }}>Save</Button>
                      <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
                    </div>
                  </div>
                ) : (
                  <pre className="mt-2 max-h-40 overflow-auto text-xs text-muted-foreground">{JSON.stringify(p.limits)}</pre>
                )}
              </div>
            ))}
          </div>
        )}
      </Loadable>
    </>
  );
}

export function Analytics() {
  const q = useAdmin<R>("/analytics");
  return (
    <>
      <PageTitle title="Analytics (30 days)" />
      <Loadable q={q}>
        {(d) => (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {Object.entries((d.funnel as R) ?? {}).map(([k, v]) => <Stat key={k} label={k.replace(/_/g, " ")} value={fmtNum(v)} />)}
            </div>
            <Bars label="Daily requests" data={((d.daily_requests as R[]) ?? []).map((r) => ({ x: fmtDate(r.day), y: Number(r.requests) }))} />
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <h2 className="mb-2 font-medium">Feedback</h2>
                <Table head={["Rating", "Count"]} rows={Object.entries((d.feedback as R) ?? {}).map(([k, v]) => [k, fmtNum(v)])} />
              </div>
              <div>
                <h2 className="mb-2 font-medium">Tools</h2>
                <Table head={["Tool", "Status", "Count"]} rows={((d.tools as R[]) ?? []).map((t) => [s(t.tool), s(t.status), fmtNum(t.count)])} />
              </div>
            </div>
          </div>
        )}
      </Loadable>
    </>
  );
}

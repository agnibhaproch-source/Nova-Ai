"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { api, type ListEnvelope } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";

import { Row, Section } from "./section";

type SessionRow = { id: string; device_label: string | null; ip_address: string | null; last_seen_at: string; is_current: boolean };

function ChangePassword() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form className="grid gap-3 px-5 py-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end" onSubmit={async (e) => {
      e.preventDefault();
      setBusy(true);
      try {
        await api("/users/me/password", { method: "POST", json: { current_password: current, new_password: next } });
        toast.success("Password changed. Other devices were signed out.");
        setCurrent(""); setNext("");
      } catch (err) { toast.error(errorMessage(err)); } finally { setBusy(false); }
    }}>
      <Field id="cur" label="Current password"><Input id="cur" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} /></Field>
      <Field id="new" label="New password"><Input id="new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} /></Field>
      <Button type="submit" variant="outline" loading={busy} disabled={!current || next.length < 12}>Update</Button>
    </form>
  );
}

function Sessions() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["sessions"], queryFn: async () => (await api<ListEnvelope<SessionRow>>("/users/me/sessions")).data });
  const revoke = async (id: string) => {
    try { await api(`/users/me/sessions/${id}`, { method: "DELETE" }); await qc.invalidateQueries({ queryKey: ["sessions"] }); }
    catch (err) { toast.error(errorMessage(err)); }
  };
  return (
    <div className="px-5 py-4">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm font-medium">Active sessions</p>
        <Button size="sm" variant="outline" onClick={async () => {
          try { await api("/users/me/sessions/revoke-others", { method: "POST" }); await qc.invalidateQueries({ queryKey: ["sessions"] }); toast.success("Signed out of other devices"); }
          catch (err) { toast.error(errorMessage(err)); }
        }}>Sign out other devices</Button>
      </div>
      <ul className="divide-y divide-border rounded-lg border border-border">
        {data?.map((s) => (
          <li key={s.id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
            <div className="min-w-0">
              <p className="truncate">{s.device_label ?? "Unknown device"} {s.is_current ? <span className="ml-1 rounded-full bg-accent px-1.5 text-xs text-primary">This device</span> : null}</p>
              <p className="text-xs text-muted-foreground">{s.ip_address ?? "—"} · active {formatDistanceToNow(new Date(s.last_seen_at), { addSuffix: true })}</p>
            </div>
            {!s.is_current ? <Button size="sm" variant="ghost" onClick={() => revoke(s.id)}>Revoke</Button> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function DeleteAccount() {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Row label="Delete account" description="Permanently delete your account and all data within 24 hours.">
      <Dialog open={open} onOpenChange={setOpen}>
        <Button variant="destructive" size="sm" onClick={() => setOpen(true)}>Delete account</Button>
        <DialogContent title="Delete your account?" description="This can't be undone. Type DELETE and enter your password to confirm.">
          <form className="space-y-3" onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            try {
              await api("/users/me", { method: "DELETE", json: { password, confirmation: confirm } });
              window.location.assign("/");
            } catch (err) { toast.error(errorMessage(err)); setBusy(false); }
          }}>
            <Field id="del-pw" label="Password"><Input id="del-pw" type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
            <Field id="del-confirm" label='Type "DELETE"'><Input id="del-confirm" value={confirm} onChange={(e) => setConfirm(e.target.value)} /></Field>
            <Button type="submit" variant="destructive" className="w-full" loading={busy} disabled={confirm !== "DELETE" || !password}>Delete permanently</Button>
          </form>
        </DialogContent>
      </Dialog>
    </Row>
  );
}

export function SecuritySettings() {
  return (
    <div className="space-y-6">
      <Section title="Password"><ChangePassword /></Section>
      <Section title="Sessions"><Sessions /></Section>
      <Section title="Danger zone"><DeleteAccount /></Section>
    </div>
  );
}

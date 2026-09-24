"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, KeyRound } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { api, type Envelope, type ListEnvelope } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";

import { Section } from "./section";

interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
}

const KEY = ["api-keys"] as const;

/** Personal API keys (docs/31 §13). The secret is shown exactly once. */
export function ApiKeysSettings() {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [secret, setSecret] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const list = useQuery({ queryKey: KEY, queryFn: async () => (await api<ListEnvelope<ApiKey>>("/api-keys")).data });
  const create = useMutation({
    mutationFn: async () => (await api<Envelope<ApiKey & { secret: string }>>("/api-keys", { method: "POST", json: { name: name.trim() } })).data,
    onSuccess: (k) => { setName(""); setSecret(k.secret); void qc.invalidateQueries({ queryKey: KEY }); },
    onError: (err) => toast.error(errorMessage(err)),
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api(`/api-keys/${id}`, { method: "DELETE" }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: KEY }); toast.success("Key revoked"); },
    onError: (err) => toast.error(errorMessage(err)),
  });

  return (
    <div className="space-y-6">
      <Section title="API keys" description="Use Nova from your own scripts with a Bearer token. Available on Plus and Pro.">
        <form className="flex gap-2 px-5 py-4" onSubmit={(e) => { e.preventDefault(); if (name.trim()) create.mutate(); }}>
          <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={64} placeholder="Key name, e.g. “laptop script”" aria-label="Key name" />
          <Button type="submit" disabled={!name.trim() || create.isPending}>Create key</Button>
        </form>
        {list.data?.length === 0 ? (
          <EmptyState icon={KeyRound} title="No API keys" description="Keys you create appear here." />
        ) : (
          list.data?.map((k) => (
            <div key={k.id} className="flex items-center gap-3 px-5 py-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{k.name}</p>
                <p className="font-mono text-xs text-muted-foreground">{k.key_prefix}…</p>
                <p className="text-xs text-muted-foreground">
                  Created {new Date(k.created_at).toLocaleDateString()} · {k.last_used_at ? `last used ${new Date(k.last_used_at).toLocaleDateString()}` : "never used"}
                </p>
              </div>
              <Button variant="outline" size="sm" onClick={() => window.confirm(`Revoke “${k.name}”? Apps using it stop working immediately.`) && revoke.mutate(k.id)}>
                Revoke
              </Button>
            </div>
          ))
        )}
      </Section>
      <Dialog open={!!secret} onOpenChange={(o) => { if (!o) { setSecret(null); setCopied(false); } }}>
        <DialogContent title="Copy your new key" description="You won't be able to see it again.">
          <div className="flex gap-2">
            <Input readOnly value={secret ?? ""} className="font-mono text-xs" aria-label="API key" />
            <Button variant="outline" size="icon" aria-label="Copy key" onClick={async () => { await navigator.clipboard.writeText(secret ?? ""); setCopied(true); }}>
              {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
            </Button>
          </div>
          <Button onClick={() => setSecret(null)}>Done</Button>
        </DialogContent>
      </Dialog>
    </div>
  );
}

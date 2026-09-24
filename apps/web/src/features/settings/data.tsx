"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { usePreferences } from "@/features/chat/api";
import { useConversations, useDeleteConversation, useRestoreConversation, useUpdateConversation } from "@/features/conversations/api";
import { api, type ListEnvelope } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";

import { Row, Section } from "./section";
import { useUpdatePreferences } from "./use-prefs";

function ConversationDialog({ kind }: { kind: "archived" | "trash" }) {
  const [open, setOpen] = useState(false);
  const q = useConversations(kind === "archived" ? { archived: true } : { deleted: true });
  const update = useUpdateConversation();
  const restore = useRestoreConversation();
  const del = useDeleteConversation();
  const items = q.data?.pages.flatMap((p) => p.data) ?? [];
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>Manage</Button>
      <DialogContent title={kind === "archived" ? "Archived chats" : "Trash"} description={kind === "trash" ? "Items are permanently deleted after 30 days." : undefined} className="md:max-w-[560px]">
        {items.length === 0 ? <p className="text-sm text-muted-foreground">Nothing here.</p> : (
          <ul className="max-h-[50vh] divide-y divide-border overflow-y-auto">
            {items.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-2 py-2 text-sm">
                <span className="min-w-0 flex-1 truncate">{c.title}</span>
                {kind === "archived" ? (
                  <Button size="sm" variant="ghost" onClick={() => update.mutate({ id: c.id, patch: { archived: false } })}>Unarchive</Button>
                ) : (
                  <>
                    <Button size="sm" variant="ghost" onClick={() => restore.mutate(c.id)}>Restore</Button>
                    <Button size="sm" variant="ghost" className="text-destructive" onClick={() => del.mutate({ id: c.id, permanent: true })}>Delete</Button>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  );
}

interface DataExport {
  id: string;
  status: "pending" | "processing" | "ready" | "failed" | "expired";
  size_bytes: number | null;
  created_at: string;
  expires_at: string | null;
}

function ExportRow() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["exports"],
    queryFn: async () => (await api<ListEnvelope<DataExport>>("/users/me/exports")).data,
    refetchInterval: (q) => (q.state.data?.some((e) => e.status === "pending" || e.status === "processing") ? 3000 : false),
  });
  const latest = data?.[0];
  const working = latest && (latest.status === "pending" || latest.status === "processing");
  return (
    <Row
      label="Export data"
      description={
        latest?.status === "ready"
          ? `Ready — expires ${latest.expires_at ? new Date(latest.expires_at).toLocaleDateString() : "soon"}. We also emailed you a link.`
          : working
            ? "Preparing your export…"
            : "Download your chats, memories and files as a .zip."
      }
    >
      {latest?.status === "ready" ? (
        <Button asChild size="sm" variant="outline">
          <a href={`/api/v1/users/me/exports/${latest.id}/download`}>Download</a>
        </Button>
      ) : (
        <Button
          size="sm"
          variant="outline"
          disabled={!!working}
          onClick={async () => {
            try { await api("/users/me/exports", { method: "POST", json: { include_files: true } }); await qc.invalidateQueries({ queryKey: ["exports"] }); }
            catch (err) { toast.error(errorMessage(err)); }
          }}
        >
          {working ? "Preparing…" : "Export"}
        </Button>
      )}
    </Row>
  );
}

export function DataSettings() {
  const qc = useQueryClient();
  const { data: prefs } = usePreferences();
  const update = useUpdatePreferences();
  return (
    <Section title="Data controls">
      <Row label="Archived chats"><ConversationDialog kind="archived" /></Row>
      <Row label="Trash" description="Deleted chats can be restored for 30 days."><ConversationDialog kind="trash" /></Row>
      <Row label="Delete all chats" description="Moves every conversation to the trash.">
        <Button variant="destructive" size="sm" onClick={async () => {
          if (!window.confirm("Move all conversations to the trash?")) return;
          try { await api("/conversations/bulk-delete", { method: "POST", json: { all: true } }); await qc.invalidateQueries({ queryKey: ["conversations"] }); toast.success("All chats moved to trash"); }
          catch (err) { toast.error(errorMessage(err)); }
        }}>Delete all</Button>
      </Row>
      <ExportRow />
      <Row label="Product analytics" description="Anonymous usage events, never message content.">
        <Switch checked={!(prefs?.analytics_opt_out ?? false)} onCheckedChange={(v) => update.mutate({ analytics_opt_out: !v })} aria-label="Share product analytics" />
      </Row>
    </Section>
  );
}

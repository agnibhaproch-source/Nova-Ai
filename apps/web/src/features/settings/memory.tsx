"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { usePreferences } from "@/features/chat/api";
import { api, type Envelope, type ListEnvelope } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";

import { Row, Section } from "./section";
import { useUpdatePreferences } from "./use-prefs";

interface Memory {
  id: string;
  content: string;
  category: string;
  source: "user" | "extracted";
  created_at: string;
}

const KEY = ["memories"] as const;

/** Memory management (docs/17 §8): view, add, edit, delete, delete all. */
export function MemorySettings() {
  const qc = useQueryClient();
  const { data: prefs } = usePreferences();
  const updatePrefs = useUpdatePreferences();
  const [q, setQ] = useState("");
  const [draft, setDraft] = useState("");
  const list = useQuery({
    queryKey: [...KEY, q],
    queryFn: async () => (await api<ListEnvelope<Memory>>(`/memories${q ? `?q=${encodeURIComponent(q)}` : ""}`)).data,
  });
  const refresh = () => qc.invalidateQueries({ queryKey: KEY });
  const onErr = (err: unknown) => toast.error(errorMessage(err));
  const add = useMutation({
    mutationFn: () => api<Envelope<Memory>>("/memories", { method: "POST", json: { content: draft.trim() } }),
    onSuccess: () => { setDraft(""); void refresh(); toast.success("Memory saved"); },
    onError: onErr,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/memories/${id}`, { method: "DELETE" }),
    onSuccess: (_d, id) => {
      void refresh();
      toast("Memory deleted", { action: { label: "Undo", onClick: () => void api(`/memories/${id}/restore`, { method: "POST" }).then(refresh) } });
    },
    onError: onErr,
  });
  const edit = useMutation({
    mutationFn: ({ id, content }: { id: string; content: string }) => api(`/memories/${id}`, { method: "PATCH", json: { content } }),
    onSuccess: () => void refresh(),
    onError: onErr,
  });

  return (
    <div className="space-y-6">
      <Section title="Memory" description="Nova can remember stable preferences and facts you share, and use them in future chats.">
        <Row label="Use memory" description="Save and reference memories across chats.">
          <Switch checked={prefs?.memory_enabled ?? true} onCheckedChange={(v) => updatePrefs.mutate({ memory_enabled: v })} aria-label="Use memory" />
        </Row>
        <form
          className="flex gap-2 px-5 py-4"
          onSubmit={(e) => { e.preventDefault(); if (draft.trim().length >= 3) add.mutate(); }}
        >
          <Input value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={500} placeholder="Add a memory, e.g. “I prefer metric units”" aria-label="New memory" />
          <Button type="submit" disabled={draft.trim().length < 3 || add.isPending}>Add</Button>
        </form>
      </Section>

      <Section title="Saved memories">
        <div className="px-5 py-3">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search memories" aria-label="Search memories" />
        </div>
        {list.data?.length === 0 ? (
          <EmptyState icon={Brain} title="No memories yet" description="Tell Nova to remember something, or add one above." />
        ) : (
          list.data?.map((m) => <MemoryRow key={m.id} m={m} onDelete={() => remove.mutate(m.id)} onSave={(content) => edit.mutate({ id: m.id, content })} />)
        )}
        {list.data?.length ? (
          <div className="flex justify-end px-5 py-3">
            <Button
              variant="destructive"
              size="sm"
              onClick={async () => {
                if (!window.confirm("Delete all memories? This can't be undone.")) return;
                try { await api("/memories", { method: "DELETE" }); await refresh(); toast.success("All memories deleted"); } catch (err) { onErr(err); }
              }}
            >
              Delete all
            </Button>
          </div>
        ) : null}
      </Section>
    </div>
  );
}

function MemoryRow({ m, onDelete, onSave }: { m: Memory; onDelete: () => void; onSave: (c: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(m.content);
  return (
    <div className="flex items-start gap-3 px-5 py-3">
      <div className="min-w-0 flex-1">
        {editing ? (
          <form onSubmit={(e) => { e.preventDefault(); setEditing(false); if (value.trim() !== m.content) onSave(value.trim()); }}>
            <Input autoFocus value={value} onChange={(e) => setValue(e.target.value)} onBlur={() => setEditing(false)} maxLength={500} aria-label="Edit memory" />
          </form>
        ) : (
          <p className="text-sm">{m.content}</p>
        )}
        <p className="text-xs text-muted-foreground">
          {m.source === "user" ? "Added by you" : "Saved from a chat"} · {new Date(m.created_at).toLocaleDateString()}
        </p>
      </div>
      <Button variant="ghost" size="icon" aria-label="Edit memory" onClick={() => { setValue(m.content); setEditing(true); }}><Pencil className="size-4" /></Button>
      <Button variant="ghost" size="icon" aria-label="Delete memory" onClick={onDelete}><Trash2 className="size-4" /></Button>
    </div>
  );
}

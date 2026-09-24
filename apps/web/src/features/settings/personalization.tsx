"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { usePreferences } from "@/features/chat/api";

import { Row, Section } from "./section";
import { useUpdatePreferences } from "./use-prefs";

function LimitedTextarea({ label, value, onSave }: { label: string; value: string; onSave: (v: string) => void }) {
  const [draft, setDraft] = useState(value);
  return (
    <div className="space-y-2 px-5 py-4">
      <div className="flex justify-between text-sm"><span className="font-medium">{label}</span><span className="text-muted-foreground">{draft.length}/1500</span></div>
      <Textarea rows={4} maxLength={1500} value={draft} aria-label={label} onChange={(e) => setDraft(e.target.value)} />
      <div className="flex justify-end">
        <Button size="sm" variant="outline" disabled={draft === value} onClick={() => onSave(draft)}>Save</Button>
      </div>
    </div>
  );
}

export function PersonalizationSettings() {
  const { data: prefs } = usePreferences();
  const update = useUpdatePreferences();
  if (!prefs) return null;
  const save = (patch: Record<string, string | null>) =>
    update.mutate(patch, { onSuccess: () => toast.success("Saved") });
  return (
    <Section title="Personalization" description="Nova uses these with every conversation.">
      <LimitedTextarea key={`instructions:${prefs.custom_instructions ?? ""}`} label="How should Nova respond?" value={prefs.custom_instructions ?? ""} onSave={(v) => save({ custom_instructions: v || null })} />
      <LimitedTextarea key={`about:${prefs.about_user ?? ""}`} label="What should Nova know about you?" value={prefs.about_user ?? ""} onSave={(v) => save({ about_user: v || null })} />
      <Row label="Memory" description="Remember stable preferences across chats. Manage them under Memory.">
        <Switch checked={prefs.memory_enabled} onCheckedChange={(v) => update.mutate({ memory_enabled: v })} aria-label="Memory" />
      </Row>
      <Row label="Web search" description="Let Nova search the web when it helps (if available on this server).">
        <Switch checked={prefs.web_search_enabled} onCheckedChange={(v) => update.mutate({ web_search_enabled: v })} aria-label="Web search" />
      </Row>
      <Row label="Code execution" description="Let Nova run Python in an isolated sandbox for math and data.">
        <Switch checked={prefs.code_execution_enabled} onCheckedChange={(v) => update.mutate({ code_execution_enabled: v })} aria-label="Code execution" />
      </Row>
    </Section>
  );
}

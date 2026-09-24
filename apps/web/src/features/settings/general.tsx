"use client";

import { Switch } from "@/components/ui/switch";
import { useModels, usePreferences } from "@/features/chat/api";
import { applyTheme, type Theme } from "@/features/user/theme";
import { cn } from "@/lib/utils";

import { Row, Section } from "./section";
import { useUpdatePreferences } from "./use-prefs";

const TIMEZONES = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : ["UTC"];

export function GeneralSettings() {
  const { data: prefs } = usePreferences();
  const { data: models } = useModels();
  const update = useUpdatePreferences();
  if (!prefs) return null;
  return (
    <Section title="General">
      <Row label="Theme">
        <div className="inline-flex rounded-lg border border-border p-0.5" role="radiogroup" aria-label="Theme">
          {(["system", "light", "dark"] as Theme[]).map((t) => (
            <button key={t} type="button" role="radio" aria-checked={prefs.theme === t}
              onClick={() => { applyTheme(t); update.mutate({ theme: t }); }}
              className={cn("rounded-md px-3 py-1 text-sm capitalize", prefs.theme === t ? "bg-accent font-medium" : "text-muted-foreground")}>
              {t}
            </button>
          ))}
        </div>
      </Row>
      <Row label="Send with Enter" description="When off, use Ctrl/⌘ + Enter to send.">
        <Switch checked={prefs.send_with_enter} onCheckedChange={(v) => update.mutate({ send_with_enter: v })} aria-label="Send with Enter" />
      </Row>
      <Row label="Default model">
        <select className="h-9 rounded-md border border-border bg-surface-raised px-2 text-sm" value={prefs.default_model_key ?? ""}
          onChange={(e) => update.mutate({ default_model_key: e.target.value || null })}>
          <option value="">Automatic</option>
          {models?.filter((m) => !m.locked).map((m) => <option key={m.key} value={m.key}>{m.display_name}</option>)}
        </select>
      </Row>
      <Row label="Timezone" description="Used for dates and sidebar grouping.">
        <select className="h-9 max-w-56 rounded-md border border-border bg-surface-raised px-2 text-sm" value={prefs.timezone}
          onChange={(e) => update.mutate({ timezone: e.target.value })}>
          {TIMEZONES.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
        </select>
      </Row>
    </Section>
  );
}

"use client";

import { useState } from "react";

import { Row, Section } from "@/features/settings/section";
import { SECTIONS } from "@/features/settings/nav";
import { SETTINGS_PAGES } from "@/features/settings/registry";
import { cn } from "@/lib/utils";

import { useQuickChat } from "./store";

const TABS: readonly (readonly [string, string])[] = [["quick", "Quick Chat"], ...SECTIONS];

/** Settings inside Quick Chat: its own options plus every section from the website's settings. */
export function QuickSettings({ standalone }: { standalone?: boolean }) {
  const [tab, setTab] = useState("quick");
  const Page = SETTINGS_PAGES[tab];
  return (
    <div className="flex flex-col">
      <nav aria-label="Quick Chat settings" className="sticky top-0 z-10 flex gap-1 overflow-x-auto border-b border-border bg-background px-2 py-2">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            aria-current={tab === key ? "page" : undefined}
            className={cn("whitespace-nowrap rounded-md px-2.5 py-1.5 text-xs hover:bg-accent", tab === key && "bg-accent font-medium")}
          >
            {label}
          </button>
        ))}
      </nav>
      <div className="p-3 [&_section]:rounded-lg">{tab === "quick" ? <QuickChatOptions standalone={standalone} /> : Page ? <Page /> : null}</div>
    </div>
  );
}

function QuickChatOptions({ standalone }: { standalone?: boolean }) {
  const { opacity, setOpacity, setPos } = useQuickChat();
  const desktop = typeof window !== "undefined" && !!window.novaDesktop;
  return (
    <div className="space-y-4">
      <Section title="Window" description="How the Quick Chat window looks.">
        <div className="space-y-2 px-5 py-4">
          <div className="flex items-center justify-between text-sm">
            <label htmlFor="qc-opacity" className="font-medium">Opacity</label>
            <span className="tabular-nums text-muted-foreground">{opacity}%</span>
          </div>
          <input
            id="qc-opacity"
            type="range"
            min={0}
            max={100}
            step={1}
            value={opacity}
            onChange={(e) => setOpacity(Number(e.target.value))}
            className="w-full accent-[var(--primary)]"
          />
          <p className="text-xs text-muted-foreground">
            {desktop
              ? "Applies to the whole desktop window."
              : "Below 20%, hovering the window shows it at 20% so you can always find it."}
          </p>
        </div>
        {!standalone ? (
          <Row label="Position" description="Drag the title bar to move it anywhere.">
            <button type="button" className="text-sm text-primary hover:underline" onClick={() => setPos(null)}>
              Reset to bottom-right
            </button>
          </Row>
        ) : null}
      </Section>
      {!desktop ? (
        <Section title="Nova for Mac" description="Open Quick Chat from any app with Option + /, even with no browser open.">
          <Row label="Desktop app" description="Floating window, screenshots with Option + \, same account and memory.">
            <a href="/download" target="_blank" rel="noreferrer" className="text-sm text-primary hover:underline">Download</a>
          </Row>
        </Section>
      ) : null}
      <Section title="Shortcuts">
        <Row label="Open / close Quick Chat" description={desktop ? "Works anywhere on your computer." : "On any Nova page, when not typing."}>
          <kbd className="rounded border border-border px-2 py-0.5 text-xs">{desktop ? "Alt + /" : "/"}</kbd>
        </Row>
        <Row label="Screenshot into Quick Chat" description="Captures the whole screen without this window, even while it's closed.">
          <kbd className="rounded border border-border px-2 py-0.5 text-xs">{desktop ? "Alt + \\" : "\\"}</kbd>
        </Row>
        {desktop ? (
          <Row label="Force quit Nova" description="Closes the whole app, not just this window. Reopen it from Applications.">
            <kbd className="rounded border border-border px-2 py-0.5 text-xs">Alt + Shift + Q</kbd>
          </Row>
        ) : null}
      </Section>
    </div>
  );
}

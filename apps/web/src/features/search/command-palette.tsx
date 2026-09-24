"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { MessageSquare, Plus, Search, Settings } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useConversations, useConversationSearch, type SearchHit } from "@/features/conversations/api";
import { cn } from "@/lib/utils";
import { useUIStore } from "@/stores/ui-store";

function Highlighted({ hit }: { hit: SearchHit }) {
  if (!hit.snippet) return null;
  const parts: React.ReactNode[] = [];
  let pos = 0;
  hit.highlights.forEach(([s, e], i) => {
    parts.push(hit.snippet!.slice(pos, s));
    parts.push(<mark key={i} className="rounded bg-primary/20 text-foreground">{hit.snippet!.slice(s, e)}</mark>);
    pos = e;
  });
  parts.push(hit.snippet.slice(pos));
  return <p className="truncate text-xs text-muted-foreground">{parts}</p>;
}

type Row = { key: string; label: string; icon: React.ReactNode; sub?: React.ReactNode; go: () => void };

export function CommandPalette() {
  const open = useUIStore((s) => s.paletteOpen);
  const setOpen = useUIStore((s) => s.setPaletteOpen);
  const router = useRouter();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [idx, setIdx] = useState(0);
  const search = useConversationSearch(debounced);
  const recent = useConversations();

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 200);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(!useUIStore.getState().paletteOpen);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setOpen]);

  const go = (href: string) => {
    setOpen(false);
    setQ("");
    router.push(href);
  };

  const rows: Row[] = useMemo(() => {
    if (debounced.trim()) {
      return (search.data ?? []).map((h) => ({
        key: h.conversation_id,
        label: h.title,
        icon: <MessageSquare className="size-4" />,
        sub: <Highlighted hit={h} />,
        go: () => go(`/c/${h.conversation_id}`),
      }));
    }
    const actions: Row[] = [
      { key: "new", label: "New chat", icon: <Plus className="size-4" />, go: () => go("/chat") },
      { key: "settings", label: "Settings", icon: <Settings className="size-4" />, go: () => go("/settings/general") },
    ];
    const rec = (recent.data?.pages[0]?.data ?? []).slice(0, 5).map((c) => ({
      key: c.id,
      label: c.title,
      icon: <MessageSquare className="size-4" />,
      go: () => go(`/c/${c.id}`),
    }));
    return [...actions, ...rec];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced, search.data, recent.data]);


  return (
    <DialogPrimitive.Root open={open} onOpenChange={setOpen}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <DialogPrimitive.Content
          className="fixed inset-x-0 top-0 z-50 flex h-dvh flex-col bg-surface-raised md:left-1/2 md:top-[20vh] md:h-auto md:max-h-[60vh] md:w-full md:max-w-[640px] md:-translate-x-1/2 md:rounded-xl md:border md:border-border md:shadow-xl"
          aria-describedby={undefined}
        >
          <DialogPrimitive.Title className="sr-only">Search chats</DialogPrimitive.Title>
          <div className="flex items-center gap-2 border-b border-border px-4">
            <Search className="size-4 text-muted-foreground" />
            <input
              autoFocus
              value={q}
              onChange={(e) => { setQ(e.target.value); setIdx(0); }}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(rows.length - 1, i + 1)); }
                if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(0, i - 1)); }
                if (e.key === "Enter") rows[Math.min(idx, rows.length - 1)]?.go();
              }}
              placeholder="Search chats…"
              className="h-12 flex-1 bg-transparent text-base outline-none"
              role="combobox"
              aria-expanded
              aria-controls="palette-results"
            />
          </div>
          <ul id="palette-results" role="listbox" className="flex-1 overflow-y-auto p-2">
            {debounced && search.isLoading ? <li className="p-3 text-sm text-muted-foreground">Searching…</li> : null}
            {debounced && !search.isLoading && rows.length === 0 ? (
              <li className="p-3 text-sm text-muted-foreground">No results</li>
            ) : null}
            {rows.map((r, i) => (
              <li
                key={r.key}
                role="option"
                aria-selected={i === Math.min(idx, rows.length - 1)}
                onMouseEnter={() => setIdx(i)}
                onClick={r.go}
                className={cn("flex cursor-pointer items-start gap-3 rounded-md px-3 py-2", i === Math.min(idx, rows.length - 1) && "bg-accent")}
              >
                <span className="mt-0.5 text-muted-foreground">{r.icon}</span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm">{r.label}</p>
                  {r.sub}
                </div>
              </li>
            ))}
          </ul>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

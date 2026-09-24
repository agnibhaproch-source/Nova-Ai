"use client";

import { create } from "zustand";

import type { Citation, Message, MessagePart } from "@/lib/types";

/** Live generation state (docs/13 §10). Server data stays in TanStack Query. */
export interface LiveTurn {
  conversationId: string;
  userMessage: Message | null;
  assistant: Message;
  text: string; // all text so far (scroll + copy)
  parts: Record<number, MessagePart>; // by part position: text, tool_call, tool_result, code
  citations: Citation[];
  stopping: boolean;
  lastEventId: number;
  error: { code: string; message: string; retryable: boolean } | null;
}

interface StreamState {
  turns: Record<string, LiveTurn>; // keyed by assistant message id
  pendingUser: { conversationId: string; content: string } | null;
  start: (t: LiveTurn) => void;
  append: (id: string, delta: string, position: number | null, eventId: number | null) => void;
  setPart: (id: string, part: MessagePart) => void;
  addCitation: (id: string, c: Citation) => void;
  patch: (id: string, patch: Partial<LiveTurn>) => void;
  remove: (id: string) => void;
  setPendingUser: (p: StreamState["pendingUser"]) => void;
}

function update(s: StreamState, id: string, fn: (t: LiveTurn) => LiveTurn | null) {
  const t = s.turns[id];
  const next = t ? fn(t) : null;
  return next ? { turns: { ...s.turns, [id]: next } } : s;
}

export const useStreamStore = create<StreamState>((set) => ({
  turns: {},
  pendingUser: null,
  start: (t) => set((s) => ({ turns: { ...s.turns, [t.assistant.id]: t }, pendingUser: null })),
  append: (id, delta, position, eventId) =>
    set((s) =>
      update(s, id, (t) => {
        if (t.stopping) return null;
        const pos = position ?? 0;
        const prev = t.parts[pos];
        const part: MessagePart = { position: pos, type: "text", text: (prev?.text ?? "") + delta };
        return {
          ...t,
          text: t.text + delta,
          parts: { ...t.parts, [pos]: part },
          lastEventId: eventId ?? t.lastEventId,
        };
      }),
    ),
  setPart: (id, part) =>
    set((s) => update(s, id, (t) => ({ ...t, parts: { ...t.parts, [part.position]: { ...t.parts[part.position], ...part } } }))),
  addCitation: (id, c) =>
    set((s) =>
      update(s, id, (t) => (t.citations.some((x) => x.index === c.index) ? null : { ...t, citations: [...t.citations, c] })),
    ),
  patch: (id, patch) => set((s) => update(s, id, (t) => ({ ...t, ...patch }))),
  remove: (id) =>
    set((s) => {
      const turns = { ...s.turns };
      delete turns[id];
      return { turns };
    }),
  setPendingUser: (p) => set({ pendingUser: p }),
}));

/** Ordered parts for rendering a live turn. */
export function liveParts(t: LiveTurn): MessagePart[] {
  return Object.values(t.parts).sort((a, b) => a.position - b.position);
}

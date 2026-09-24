"use client";

import { create } from "zustand";

/** Quick Chat popup state; lives across route changes (docs/27 §17a). */
export interface Pos {
  x: number;
  y: number;
}

interface QuickChatState {
  open: boolean;
  conversationId: string | null;
  pos: Pos | null; // top-left of the floating window; null = default (bottom-right)
  setPos: (p: Pos | null) => void;
  opacity: number; // 0–100 (docs/27 §17a)
  setOpacity: (v: number) => void;
  capturing: boolean; // hide the window while a screenshot is taken
  setCapturing: (v: boolean) => void;
  shots: File[]; // screenshots waiting for the Quick Chat composer
  addShot: (f: File) => void;
  takeShots: () => File[];
  setOpen: (v: boolean) => void;
  toggle: () => void;
  setConversation: (id: string | null) => void;
}

const POS_KEY = "nova-quick-chat-pos";
const OPACITY_KEY = "nova-quick-chat-opacity";

function readNumber(key: string, fallback: number): number {
  if (typeof window === "undefined") return fallback;
  try {
    const v = Number(localStorage.getItem(key));
    return localStorage.getItem(key) !== null && Number.isFinite(v) ? v : fallback;
  } catch {
    return fallback;
  }
}
const CONV_KEY = "nova-quick-chat-conversation";

function readConversation(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const v = localStorage.getItem(CONV_KEY);
    return v && /^[0-9a-f-]{36}$/.test(v) ? v : null;
  } catch {
    return null;
  }
}

function readPos(): Pos | null {
  if (typeof window === "undefined") return null;
  try {
    const v = JSON.parse(localStorage.getItem(POS_KEY) ?? "null") as Pos | null;
    return v && Number.isFinite(v.x) && Number.isFinite(v.y) ? v : null;
  } catch {
    return null;
  }
}

export const useQuickChat = create<QuickChatState>((set) => ({
  open: false,
  conversationId: readConversation(),
  pos: readPos(),
  opacity: readNumber(OPACITY_KEY, 100),
  setOpacity: (v) => {
    const opacity = Math.max(0, Math.min(100, Math.round(v)));
    try {
      localStorage.setItem(OPACITY_KEY, String(opacity));
    } catch {
      /* storage unavailable */
    }
    window.novaDesktop?.setOpacity(opacity / 100);
    set({ opacity });
  },
  capturing: false,
  setCapturing: (capturing) => set({ capturing }),
  shots: [],
  addShot: (f) => set((st) => ({ shots: [...st.shots, f] })),
  takeShots: () => {
    let taken: File[] = [];
    set((st) => {
      taken = st.shots;
      return { shots: [] };
    });
    return taken;
  },
  setPos: (pos) => {
    try {
      if (pos) localStorage.setItem(POS_KEY, JSON.stringify(pos));
      else localStorage.removeItem(POS_KEY);
    } catch {
      /* storage unavailable: position just isn't remembered */
    }
    set({ pos });
  },
  setOpen: (open) => set({ open }),
  toggle: () => set((s) => ({ open: !s.open })),
  setConversation: (conversationId) => {
    // Shared by the in-page popup, the pop-out window and the browser extension window.
    try {
      if (conversationId) localStorage.setItem(CONV_KEY, conversationId);
      else localStorage.removeItem(CONV_KEY);
    } catch {
      /* storage unavailable */
    }
    set({ conversationId });
  },
}));

/**
 * True when a keypress is going into a field and must not trigger shortcuts. The main
 * composer is focused by default, so "/" in it still opens Quick Chat while it's empty.
 */
export function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target instanceof HTMLTextAreaElement && target.dataset.quickChatTrigger === "empty" && target.value === "") return false;
  return !!target.closest("input,textarea,select,[contenteditable=''],[contenteditable='true']");
}

"use client";

import { create } from "zustand";

interface UIState {
  sidebarOpen: boolean; // mobile/tablet drawer
  sidebarCollapsed: boolean; // desktop
  paletteOpen: boolean;
  setSidebarOpen: (v: boolean) => void;
  toggleCollapsed: () => void;
  setPaletteOpen: (v: boolean) => void;
}

function readCollapsed(): boolean {
  try {
    return localStorage.getItem("nova-sidebar-collapsed") === "1";
  } catch {
    return false;
  }
}

export const useUIStore = create<UIState>((set, get) => ({
  sidebarOpen: false,
  sidebarCollapsed: typeof window !== "undefined" ? readCollapsed() : false,
  paletteOpen: false,
  setSidebarOpen: (v) => set({ sidebarOpen: v }),
  toggleCollapsed: () => {
    const next = !get().sidebarCollapsed;
    try {
      localStorage.setItem("nova-sidebar-collapsed", next ? "1" : "0");
    } catch {
      /* storage unavailable */
    }
    set({ sidebarCollapsed: next });
  },
  setPaletteOpen: (v) => set({ paletteOpen: v }),
}));

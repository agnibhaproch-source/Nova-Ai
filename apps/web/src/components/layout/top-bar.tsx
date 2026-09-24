"use client";

import { Menu, MessageSquareDashed, PanelLeftOpen, SquarePen } from "lucide-react";
import Link from "next/link";

import { cn } from "@/lib/utils";
import { useQuickChat } from "@/features/quick-chat/store";
import { useUIStore } from "@/stores/ui-store";

export function TopBar({ children, title }: { children?: React.ReactNode; title?: string }) {
  const { setSidebarOpen, sidebarCollapsed, toggleCollapsed } = useUIStore();
  const toggleQuick = useQuickChat((s) => s.toggle);
  return (
    <header className="sticky top-0 z-10 flex h-13 shrink-0 items-center gap-1 bg-background/85 px-2 backdrop-blur-md md:h-14 md:px-3">
      <button type="button" aria-label="Open sidebar" onClick={() => setSidebarOpen(true)} className="rounded-md p-2 text-muted-foreground hover:bg-accent lg:hidden">
        <Menu className="size-5" />
      </button>
      <button
        type="button"
        aria-label="Open sidebar"
        onClick={toggleCollapsed}
        className={cn("hidden rounded-md p-2 text-muted-foreground hover:bg-accent", sidebarCollapsed && "lg:block")}
      >
        <PanelLeftOpen className="size-5" />
      </button>
      <div className="flex min-w-0 flex-1 items-center gap-1">
        {title ? <h1 className="truncate px-2 text-sm font-medium">{title}</h1> : null}
        {children}
      </div>
      <button
        type="button"
        onClick={toggleQuick}
        aria-label="Quick Chat"
        title="Quick Chat (press /)"
        className="flex items-center gap-1.5 rounded-md p-2 text-sm text-muted-foreground hover:bg-accent"
      >
        <MessageSquareDashed className="size-5" />
        <kbd className="hidden rounded border border-border px-1.5 text-xs md:inline">/</kbd>
      </button>
      <Link href="/chat" aria-label="New chat" className="rounded-md p-2 text-muted-foreground hover:bg-accent lg:hidden">
        <SquarePen className="size-5" />
      </Link>
    </header>
  );
}

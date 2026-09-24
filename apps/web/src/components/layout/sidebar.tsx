"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { PanelLeftClose, Search, SquarePen } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Logo } from "@/components/common/logo";
import { Button } from "@/components/ui/button";
import { ConversationList } from "@/features/conversations/conversation-list";
import { cn } from "@/lib/utils";
import { useUIStore } from "@/stores/ui-store";

import { UserMenu } from "./user-menu";

function SidebarBody({ onNavigate, onCollapse }: { onNavigate?: () => void; onCollapse?: () => void }) {
  const setPalette = useUIStore((s) => s.setPaletteOpen);
  return (
    <div className="flex h-full flex-col bg-surface">
      <div className="flex h-14 items-center justify-between px-3">
        <Link href="/chat" onClick={onNavigate} aria-label="New chat"><Logo /></Link>
        {onCollapse ? (
          <button type="button" onClick={onCollapse} aria-label="Close sidebar" className="rounded-md p-1.5 text-muted-foreground hover:bg-accent">
            <PanelLeftClose className="size-5" />
          </button>
        ) : null}
      </div>
      <div className="space-y-1 px-2 pb-3">
        <Button asChild variant="outline" className="w-full justify-start">
          <Link href="/chat" onClick={onNavigate}><SquarePen /> New chat</Link>
        </Button>
        <Button variant="ghost" className="w-full justify-start text-muted-foreground" onClick={() => setPalette(true)}>
          <Search /> Search chats
          <kbd className="ml-auto text-xs">⌘K</kbd>
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto pb-4">
        <ConversationList onNavigate={onNavigate} />
      </div>
      <div className="border-t border-border p-2"><UserMenu /></div>
    </div>
  );
}

export function Sidebar() {
  const { sidebarOpen, setSidebarOpen, sidebarCollapsed, toggleCollapsed } = useUIStore();
  const router = useRouter();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.shiftKey && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (window.innerWidth >= 1024) toggleCollapsed();
        else setSidebarOpen(!useUIStore.getState().sidebarOpen);
      }
      if (mod && e.shiftKey && e.key.toLowerCase() === "o") {
        e.preventDefault();
        router.push("/chat");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router, setSidebarOpen, toggleCollapsed]);

  return (
    <>
      <aside
        className={cn(
          "hidden shrink-0 border-r border-border transition-[width] duration-200 lg:block lg:w-[260px] xl:w-[272px] 2xl:w-[288px]",
          sidebarCollapsed && "lg:w-0 xl:w-0 2xl:w-0 lg:overflow-hidden lg:border-r-0",
        )}
      >
        <SidebarBody onCollapse={toggleCollapsed} />
      </aside>
      <DialogPrimitive.Root open={sidebarOpen} onOpenChange={setSidebarOpen}>
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/40 lg:hidden" />
          <DialogPrimitive.Content
            aria-describedby={undefined}
            className="fixed inset-y-0 left-0 z-50 w-[min(85vw,320px)] shadow-xl md:w-72 lg:hidden"
          >
            <DialogPrimitive.Title className="sr-only">Navigation</DialogPrimitive.Title>
            <SidebarBody onNavigate={() => setSidebarOpen(false)} />
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      </DialogPrimitive.Root>
    </>
  );
}

"use client";

import { ExternalLink, GripHorizontal, History, Maximize2, MessageSquare, Minus, Settings, SquarePen, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { ChatView } from "@/features/chat/components/chat-view";
import { useConversations } from "@/features/conversations/api";
import { useUser } from "@/features/user/user-context";
import { cn } from "@/lib/utils";
import { useStreamStore } from "@/stores/stream-store";

import { queueScreenshot } from "./capture";
import { QuickSettings } from "./quick-settings";
import { isTyping, type Pos, useQuickChat } from "./store";

/**
 * Quick Chat: a small floating chat workspace over any page, toggled with "/" (docs/27 §17a).
 * It runs its own conversation (created in the popup, without navigating the main page) and
 * can be expanded to the full chat view or popped out into its own small window (/quick).
 */
const MARGIN = 8;

function panelSize() {
  const w = Math.min(420, window.innerWidth - MARGIN * 2);
  const h = Math.min(640, window.innerHeight - MARGIN * 2);
  return { w, h };
}

function clamp(p: Pos, w: number, h: number): Pos {
  return {
    x: Math.min(Math.max(MARGIN, p.x), Math.max(MARGIN, window.innerWidth - w - MARGIN)),
    y: Math.min(Math.max(MARGIN, p.y), Math.max(MARGIN, window.innerHeight - h - MARGIN)),
  };
}

const defaultPos = (w: number, h: number): Pos => ({ x: window.innerWidth - w - 20, y: window.innerHeight - h - 20 });

export function QuickChatLauncher() {
  const { open, toggle, setOpen, pos, setPos, opacity, capturing } = useQuickChat();
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const drag = useRef<{ dx: number; dy: number; id: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [livePos, setLivePos] = useState<Pos | null>(null); // while dragging; saved on release

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.key !== "/" && e.key !== "\\") || e.metaKey || e.ctrlKey || e.altKey || e.isComposing || isTyping(e.target)) return;
      if (document.querySelector('[role=dialog]:not([aria-label="Quick Chat"])')) return; // not over modals
      e.preventDefault();
      if (e.key === "\\") void queueScreenshot(); // screenshot → Quick Chat, window stays as it is
      else toggle();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle]);

  // Track viewport size so the window always stays fully on screen.
  useEffect(() => {
    if (!open) return;
    const onResize = () => setSize(panelSize());
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [open]);

  if (!open || !size) return null;
  const at = clamp(livePos ?? pos ?? defaultPos(size.w, size.h), size.w, size.h);

  const handle: DragHandle = {
    onPointerDown: (e) => {
      if (e.button !== 0 || (e.target as HTMLElement).closest("button,a")) return;
      e.currentTarget.setPointerCapture(e.pointerId);
      drag.current = { dx: e.clientX - at.x, dy: e.clientY - at.y, id: e.pointerId };
      setDragging(true);
    },
    onPointerMove: (e) => {
      const d = drag.current;
      if (!d || d.id !== e.pointerId) return;
      setLivePos(clamp({ x: e.clientX - d.dx, y: e.clientY - d.dy }, size.w, size.h));
    },
    onPointerCancel: (e) => handle.onPointerUp(e),
    onPointerUp: (e) => {
      if (drag.current?.id !== e.pointerId) return;
      drag.current = null;
      if (livePos) setPos(livePos);
      setLivePos(null);
      setDragging(false);
    },
    onDoubleClick: (e) => {
      if (!(e.target as HTMLElement).closest("button,a")) setPos(null); // snap back to bottom-right
    },
    onKeyDown: (e) => {
      const step = e.shiftKey ? 64 : 16;
      const delta: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
      const d = delta[e.key];
      if (!d) return;
      e.preventDefault();
      setPos(clamp({ x: at.x + d[0], y: at.y + d[1] }, size.w, size.h));
    },
  };

  return (
    <div
      className={cn(
        "fixed z-40 transition-opacity",
        dragging && "select-none",
        // Very low opacity: hovering reveals it at 20% so it can always be found again.
        opacity < 20 && "hover:!opacity-20",
      )}
      style={{
        left: at.x,
        top: at.y,
        width: size.w,
        height: size.h,
        opacity: opacity / 100,
        visibility: capturing ? "hidden" : undefined, // never in our own screenshots
      }}
      role="dialog"
      aria-modal="false"
      aria-label="Quick Chat"
    >
      <QuickChatPanel onClose={() => setOpen(false)} dragHandle={handle} dragging={dragging} />
    </div>
  );
}

export interface DragHandle {
  onPointerDown: (e: React.PointerEvent<HTMLDivElement>) => void;
  onPointerMove: (e: React.PointerEvent<HTMLDivElement>) => void;
  onPointerUp: (e: React.PointerEvent<HTMLDivElement>) => void;
  onPointerCancel: (e: React.PointerEvent<HTMLDivElement>) => void;
  onDoubleClick: (e: React.MouseEvent<HTMLDivElement>) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLDivElement>) => void;
}

export function QuickChatPanel({
  onClose,
  standalone,
  dragHandle,
  dragging,
}: {
  onClose?: () => void;
  standalone?: boolean;
  dragHandle?: DragHandle;
  dragging?: boolean;
}) {
  const user = useUser();
  const { conversationId, setConversation } = useQuickChat();
  const panel = useRef<HTMLDivElement>(null);
  const busy = useStreamStore((s) => Object.values(s.turns).some((t) => t.conversationId === conversationId));
  const [view, setView] = useState<"chat" | "settings" | "history">("chat");
  const resetConversation = useCallback(() => setConversation(null), [setConversation]);
  // Desktop app (no title bar): macOS draws its own close/minimize on hover at the top-left;
  // Windows/Linux get ours. Read after mount so server and client render the same markup.
  const bridgePlatform = useSyncExternalStore(
    noSubscribe,
    () => window.novaDesktop?.platform ?? null,
    () => null,
  );
  const desktopPlatform = standalone ? bridgePlatform : null;
  const inDesktop = desktopPlatform !== null;

  // Esc closes the popup unless a reply is streaming (then the composer's Esc stops it).
  useEffect(() => {
    if (!onClose) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy && panel.current?.contains(document.activeElement)) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, busy]);

  const popOut = () => {
    window.open(`/quick${conversationId ? `?c=${conversationId}` : ""}`, "nova-quick-chat", "popup,width=440,height=680");
    onClose?.();
  };

  return (
    <div
      ref={panel}
      className={cn(
        "group/panel relative flex h-full flex-col overflow-hidden bg-background",
        !standalone && "rounded-2xl border border-border shadow-2xl",
        dragging && "ring-2 ring-primary/30",
      )}
    >
      {/* No header bar: the controls float over the top edge and only show while hovering the
          window (or when focused from the keyboard). The strip also moves the window. */}
      <div
        {...dragHandle}
        tabIndex={dragHandle ? 0 : undefined}
        aria-label={dragHandle ? "Move Quick Chat: drag, or use arrow keys. Double-click to reset." : undefined}
        title={dragHandle ? "Drag to move · double-click to reset" : undefined}
        style={inDesktop ? ({ WebkitAppRegion: "drag" } as React.CSSProperties) : undefined}
        className={cn(
          "absolute inset-x-0 top-0 z-20 flex h-10 items-center gap-0.5 px-2 opacity-0 outline-none transition-opacity duration-150",
          "bg-background/85 backdrop-blur-sm group-hover/panel:opacity-100 focus-within:opacity-100 focus-visible:opacity-100",
          dragging && "opacity-100",
          dragHandle && "cursor-grab touch-none",
          dragging && "cursor-grabbing",
        )}
      >
        {dragHandle ? <GripHorizontal className="size-4 text-muted-foreground" aria-hidden /> : null}
        <div className="flex-1" />
        <HeaderButton label={view === "history" ? "Back to chat" : "Chat history"} onClick={() => setView((v) => (v === "history" ? "chat" : "history"))}>
          {view === "history" ? <MessageSquare /> : <History />}
        </HeaderButton>
        <HeaderButton label={view === "settings" ? "Back to chat" : "Settings"} onClick={() => setView((v) => (v === "settings" ? "chat" : "settings"))}>
          {view === "settings" ? <MessageSquare /> : <Settings />}
        </HeaderButton>
        <HeaderButton label="New quick chat" onClick={() => { setConversation(null); setView("chat"); }} disabled={busy}>
          <SquarePen />
        </HeaderButton>
        {conversationId ? (
          <HeaderButton label="Open in full view" asLink={`/c/${conversationId}`} onClick={onClose}>
            <Maximize2 />
          </HeaderButton>
        ) : null}
        {!standalone ? (
          <>
            <HeaderButton label="Pop out into a window" onClick={popOut}>
              <ExternalLink />
            </HeaderButton>
            <HeaderButton label="Close (Esc)" onClick={onClose}>
              <X />
            </HeaderButton>
          </>
        ) : null}
        {inDesktop && desktopPlatform !== "darwin" ? (
          <>
            <HeaderButton label="Minimize" onClick={() => window.novaDesktop?.minimize()}>
              <Minus />
            </HeaderButton>
            <HeaderButton label="Close" onClick={() => window.novaDesktop?.hide()}>
              <X />
            </HeaderButton>
          </>
        ) : null}
      </div>
      <div className={cn("min-h-0 flex-1 overflow-y-auto pt-10", view !== "settings" && "hidden")}>
        {view === "settings" ? <QuickSettings standalone={standalone} /> : null}
      </div>
      <div className={cn("min-h-0 flex-1 overflow-y-auto pt-10", view !== "history" && "hidden")}>
        {view === "history" ? (
          <QuickHistory
            current={conversationId}
            onPick={(id) => {
              setConversation(id);
              setView("chat");
            }}
          />
        ) : null}
      </div>
      <div className={cn("flex min-h-0 flex-1 flex-col", view !== "chat" && "hidden")}>
        <ChatView
          key={conversationId ?? "quick-new"}
          conversationId={conversationId}
          userName={user.display_name}
          compact
          onCreated={setConversation}
          onMissing={resetConversation}
        />
      </div>
    </div>
  );
}

const noSubscribe = () => () => {};

/** Every saved chat (the same list as the website's sidebar), newest first; pick one to continue it. */
function QuickHistory({ current, onPick }: { current: string | null; onPick: (id: string) => void }) {
  const list = useConversations();
  const chats = list.data?.pages.flatMap((p) => p.data) ?? [];
  if (list.isPending) return <p className="px-4 py-3 text-sm text-muted-foreground">Loading chats…</p>;
  if (!chats.length) return <p className="px-4 py-3 text-sm text-muted-foreground">No chats yet.</p>;
  return (
    <nav aria-label="Chat history" className="flex flex-col gap-0.5 px-2 pb-3">
      {chats.map((c) => (
        <button
          key={c.id}
          type="button"
          data-conversation-id={c.id}
          onClick={() => onPick(c.id)}
          aria-current={c.id === current ? "true" : undefined}
          className={cn(
            "flex flex-col rounded-md px-3 py-2 text-left hover:bg-accent",
            c.id === current && "bg-accent",
          )}
        >
          <span className="truncate text-sm">{c.title}</span>
          <span className="text-xs text-muted-foreground">{new Date(c.last_message_at).toLocaleString()}</span>
        </button>
      ))}
      {list.hasNextPage ? (
        <button type="button" onClick={() => void list.fetchNextPage()} disabled={list.isFetchingNextPage} className="px-3 py-2 text-left text-sm text-primary hover:underline">
          {list.isFetchingNextPage ? "Loading…" : "Show more"}
        </button>
      ) : null}
    </nav>
  );
}

function HeaderButton({
  label,
  onClick,
  disabled,
  asLink,
  children,
}: {
  label: string;
  onClick?: () => void;
  disabled?: boolean;
  asLink?: string;
  children: React.ReactNode;
}) {
  const cls = "flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent disabled:opacity-40 [&_svg]:size-4";
  // Buttons stay clickable inside the desktop app's window-drag strip.
  const noDrag = { WebkitAppRegion: "no-drag" } as React.CSSProperties;
  return asLink ? (
    <Link href={asLink} aria-label={label} title={label} onClick={onClick} className={cls} style={noDrag}>
      {children}
    </Link>
  ) : (
    <button type="button" aria-label={label} title={label} onClick={onClick} disabled={disabled} className={cls} style={noDrag}>
      {children}
    </button>
  );
}

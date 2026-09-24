"use client";

import { useEffect, useSyncExternalStore } from "react";

import { fileFromDataUrl, queueScreenshot } from "./capture";
import { QuickChatPanel } from "./quick-chat";
import { isTyping, useQuickChat } from "./store";

const noop = () => () => {};

/** Standalone Quick Chat (/quick): pop-out window, browser-extension window, desktop app. */
export function QuickWindow({ initialConversationId }: { initialConversationId: string | null }) {
  const setConversation = useQuickChat((s) => s.setConversation);
  const opacity = useQuickChat((s) => s.opacity);
  const desktop = typeof window !== "undefined" && !!window.novaDesktop;

  // ?c= picks a specific chat (Pop out); otherwise resume the last Quick Chat.
  useEffect(() => {
    if (initialConversationId) setConversation(initialConversationId);
  }, [initialConversationId, setConversation]);

  // Desktop app: native window opacity, and screenshots taken by its global shortcut.
  useEffect(() => {
    const d = window.novaDesktop;
    if (!d) return;
    d.setOpacity(useQuickChat.getState().opacity / 100);
    return d.onScreenshot((dataUrl) => useQuickChat.getState().addShot(fileFromDataUrl(dataUrl)));
  }, []);

  // "\\" in this window (pop-out, extension, desktop app): screenshot straight into the composer.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "\\" || e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return;
      e.preventDefault();
      void queueScreenshot();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // The remembered chat lives in localStorage, so render only in the browser (no SSR mismatch).
  const mounted = useSyncExternalStore(noop, () => true, () => false);
  if (!mounted) return <div className="h-dvh bg-background" />;
  return (
    <div className="h-dvh" style={desktop ? undefined : { opacity: opacity / 100 }}>
      <QuickChatPanel standalone />
    </div>
  );
}

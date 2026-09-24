"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowDown, Paperclip } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/common/states";
import { Skeleton } from "@/components/ui/skeleton";
import { useCreateConversation } from "@/features/conversations/api";
import { ApiError, errorMessage } from "@/lib/api/errors";
import { cn } from "@/lib/utils";
import type { Message } from "@/lib/types";
import { useStreamStore } from "@/stores/stream-store";

import { attach, sendMessage, stopGeneration } from "../actions";
import { useMessages } from "../api";
import { groqKeyKeys, looksLikeGroqKey, NewChatKeyField, ReenterKeyBar, useGroqKeyStatus, useKeyMode } from "../groq-key";
import { AssistantMessage } from "./assistant-message";
import { Composer, type SendExtras } from "./composer";
import { EmptyChat } from "./empty-chat";
import { UserMessage } from "./user-message";

function placeholderUser(cid: string, content: string): Message {
  return {
    id: "pending-user",
    conversation_id: cid,
    role: "user",
    status: "completed",
    parent_message_id: null,
    created_at: new Date().toISOString(),
    completed_at: null,
    model_key: null,
    finish_reason: null,
    error: null,
    parts: [{ position: 0, type: "text", text: content }],
    siblings: { index: 0, count: 1, prev_id: null, next_id: null },
    feedback: null,
    usage: null,
  };
}

export function ChatView({ conversationId, userName, modelKey, compact, onCreated, onMissing }: {
  conversationId: string | null;
  userName: string;
  modelKey?: string | null;
  /** Quick Chat popup: tighter layout, and new chats stay in the popup instead of navigating. */
  compact?: boolean;
  onCreated?: (cid: string) => void;
  /** The conversation doesn't exist (deleted or wrong link); Quick Chat starts a new one. */
  onMissing?: () => void;
}) {
  const qc = useQueryClient();
  const router = useRouter();
  const create = useCreateConversation();
  const { data, isLoading, error, refetch } = useMessages(conversationId);
  const missing = !!conversationId && error instanceof ApiError && error.status === 404;
  useEffect(() => {
    if (missing) onMissing?.();
  }, [missing, onMissing]);
  const turns = useStreamStore((s) => s.turns);
  const pendingUser = useStreamStore((s) => s.pendingUser);
  const scroller = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);
  const { data: keyMode } = useKeyMode();
  const { data: keyStatus } = useGroqKeyStatus(conversationId);
  const [newKey, setNewKey] = useState("");
  const byok = keyMode !== "server"; // until the mode loads, assume a key is needed
  const needsNewKey = byok && !conversationId;
  const needsReentry = byok && !!conversationId && keyStatus?.configured === false;

  const live = useMemo(
    () => Object.values(turns).filter((t) => t.conversationId === conversationId),
    [turns, conversationId],
  );
  const busy = live.length > 0 || (!!pendingUser && pendingUser.conversationId === conversationId);

  // Merge server path with live turns (docs/13 §10).
  const messages = useMemo(() => {
    const list = [...(data?.data ?? [])];
    const ids = new Set(list.map((m) => m.id));
    for (const t of live) {
      if (t.userMessage && !ids.has(t.userMessage.id)) list.push(t.userMessage);
      if (!ids.has(t.assistant.id)) list.push(t.assistant);
    }
    if (pendingUser && pendingUser.conversationId === conversationId && live.length === 0) {
      list.push(placeholderUser(pendingUser.conversationId, pendingUser.content));
    }
    return list;
  }, [data, live, pendingUser, conversationId]);

  // Resume an in-progress generation after reload.
  useEffect(() => {
    const active = data?.meta?.active_generation_message_id;
    if (conversationId && active && !turns[active]) void attach(qc, conversationId, active);
  }, [data, conversationId, qc, turns]);

  // Stick to bottom while the user is near it (docs/13 §10).
  const lastText = live[0]?.text.length ?? 0;
  useEffect(() => {
    const el = scroller.current;
    if (el && atBottom) el.scrollTop = el.scrollHeight;
  }, [messages.length, lastText, atBottom]);

  const onSend = async (text: string, extras: SendExtras = { fileIds: [], tools: {} }) => {
    let cid = conversationId;
    if (!cid) {
      try {
        if (needsNewKey && !looksLikeGroqKey(newKey)) {
          toast.error("Paste your Groq API key (starts with gsk_) to start this chat.");
          return false;
        }
        cid = (
          await create.mutateAsync({
            modelKey: modelKey ?? undefined,
            groqApiKey: needsNewKey ? newKey.trim() : undefined,
          })
        ).id;
        setNewKey("");
      } catch (err) {
        toast.error(errorMessage(err));
        return false;
      }
      useStreamStore.getState().setPendingUser({ conversationId: cid, content: text });
      if (onCreated) onCreated(cid);
      else router.replace(`/c/${cid}`);
    }
    const ok = await sendMessage(qc, cid, text, { fileIds: extras.fileIds, tools: extras.tools, onError: onKeyError(cid) });
    return ok;
  };

  // A 428 means the chat's key expired server-side: show the re-entry bar.
  const onKeyError = (cid: string) => (err: unknown) => {
    if (err instanceof ApiError && err.code === "GROQ_KEY_REQUIRED") {
      void qc.invalidateQueries({ queryKey: groqKeyKeys.status(cid) });
    }
  };

  const onStop = () => live.forEach((t) => void stopGeneration(t.assistant.id));

  // Drag and drop: files dropped anywhere on the chat (messages or composer) are attached.
  const attachRef = useRef<((files: File[]) => void) | null>(null);
  const [dragDepth, setDragDepth] = useState(0);
  const hasFiles = (e: React.DragEvent) => Array.from(e.dataTransfer.types).includes("Files");
  const dropProps = {
    onDragEnter: (e: React.DragEvent) => {
      if (!hasFiles(e) || !attachRef.current) return;
      e.preventDefault();
      setDragDepth((d) => d + 1);
    },
    onDragOver: (e: React.DragEvent) => {
      if (!hasFiles(e) || !attachRef.current) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
    },
    onDragLeave: (e: React.DragEvent) => {
      if (hasFiles(e)) setDragDepth((d) => Math.max(0, d - 1));
    },
    onDrop: (e: React.DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault(); // never let the browser / desktop window navigate to the file
      setDragDepth(0);
      if (e.dataTransfer.files.length) attachRef.current?.(Array.from(e.dataTransfer.files));
    },
  };

  return (
    <div className="relative flex min-h-0 flex-1 flex-col" data-chat-view="" {...dropProps}>
      {dragDepth > 0 ? (
        <div className="pointer-events-none absolute inset-2 z-30 flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-primary bg-background/90 text-sm font-medium">
          <Paperclip className="size-5 text-primary" aria-hidden />
          Drop files to attach
        </div>
      ) : null}
      <div
        ref={scroller}
        className="relative min-h-0 flex-1 overflow-y-auto overflow-x-hidden"
        onScroll={(e) => {
          const el = e.currentTarget;
          setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80);
        }}
      >
        {!conversationId && messages.length === 0 ? (
          <EmptyChat name={userName.split(" ")[0] ?? userName} compact={compact} />
        ) : isLoading ? (
          <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">
            <Skeleton className="ml-auto h-10 w-1/2" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="ml-auto h-10 w-1/3" />
          </div>
        ) : missing ? (
          <div className="flex flex-col items-center gap-2 px-6 py-16 text-center" role="alert">
            <h2 className="font-semibold">This chat doesn&apos;t exist</h2>
            <p className="text-sm text-muted-foreground">It may have been deleted, or the link is wrong.</p>
            <Link href="/chat" className="mt-2 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground">
              Start a new chat
            </Link>
          </div>
        ) : error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : (
          <div role="log" aria-live="off" className={cn("mx-auto w-full max-w-3xl space-y-6 px-3 py-6 md:px-6", compact && "pt-11")}>
            {messages.map((m, i) => {
              const t = turns[m.id];
              return m.role === "user" ? (
                <UserMessage key={m.id} message={m} busy={busy} />
              ) : (
                <AssistantMessage
                  key={m.id}
                  message={m}
                  live={t}
                  liveText={t?.text}
                  liveError={t?.error ?? null}
                  isLast={i === messages.length - 1}
                  busy={busy}
                />
              );
            })}
          </div>
        )}
        {!atBottom ? (
          <button
            type="button"
            aria-label="Jump to latest"
            onClick={() => scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" })}
            className="sticky bottom-3 left-1/2 flex size-9 -translate-x-1/2 items-center justify-center rounded-full border border-border bg-surface-raised shadow"
          >
            <ArrowDown className="size-4" />
          </button>
        ) : null}
      </div>
      {needsNewKey ? <NewChatKeyField value={newKey} onChange={setNewKey} /> : null}
      {needsReentry && conversationId && !missing ? <ReenterKeyBar cid={conversationId} /> : null}
      {missing ? null : <Composer key={conversationId ?? "new"} draftKey={`${compact ? "quick:" : ""}${conversationId ?? "new"}`} conversationId={conversationId} compact={compact} busy={busy} onSend={onSend} onStop={onStop} autoFocus attachRef={attachRef} />}
      <span className="sr-only" aria-live="polite">{busy ? "" : messages.length ? "Response complete" : ""}</span>
    </div>
  );
}

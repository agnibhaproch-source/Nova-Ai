"use client";

import { useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Check, Copy, RefreshCw, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";

import { LogoMark } from "@/components/common/logo";
import { Button } from "@/components/ui/button";
import { citationsOf, messageText, type Message } from "@/lib/types";
import { liveParts, type LiveTurn } from "@/stores/stream-store";
import { cn } from "@/lib/utils";

import { regenerate, sendFeedback, sendMessage } from "../actions";
import { BranchNavigator } from "./branch-navigator";
import { IconButton } from "./icon-button";
import { MessageParts } from "./message-parts";
import { ReadAloud } from "./voice";

interface Props {
  message: Message;
  live?: LiveTurn;
  liveText?: string;
  liveError?: { code: string; message: string; retryable: boolean } | null;
  isLast: boolean;
  busy: boolean;
}

function TypingDots() {
  return (
    <span className="inline-flex gap-1 py-2" aria-label="Nova is thinking">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="size-1.5 rounded-full bg-muted-foreground"
          style={{ animation: `nova-dot 1.2s ${i * 0.15}s infinite ease-in-out` }}
        />
      ))}
    </span>
  );
}

export function AssistantMessage({ message, live: liveTurn, liveText, liveError, isLast, busy }: Props) {
  const qc = useQueryClient();
  const [copied, setCopied] = useState(false);
  const [rating, setRating] = useState(message.feedback?.rating ?? null);
  const live = liveText !== undefined;
  const text = live ? liveText : messageText(message);
  const status = message.status;
  const streaming = live && !liveError;
  const error = liveError ?? message.error;
  const terminal = !live && ["completed", "cancelled", "failed"].includes(status);
  const parts = liveTurn ? liveParts(liveTurn) : message.parts.filter((p) => p.type !== "citation");
  const citations = liveTurn ? liveTurn.citations : citationsOf(message);

  return (
    <div className="group flex gap-4" aria-busy={streaming}>
      <LogoMark className="mt-1 hidden size-6 shrink-0 lg:block" />
      <div className="min-w-0 flex-1 space-y-2">
        {parts.some((p) => p.type !== "citation") ? (
          <MessageParts parts={parts} streaming={streaming} citations={citations} />
        ) : streaming || status === "pending" || status === "streaming" ? (
          <TypingDots />
        ) : null}

        {status === "cancelled" && !live ? <p className="text-xs text-muted-foreground">Stopped</p> : null}
        {status === "completed" && message.finish_reason === "length" && !live ? (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            Response reached the length limit.
            <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => sendMessage(qc, message.conversation_id, "Continue")}>
              Continue
            </Button>
          </div>
        ) : null}
        {error && (status === "failed" || liveError) ? (
          <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm">
            <AlertCircle className="size-4 text-destructive" />
            <span className="flex-1">{error.message}</span>
            {terminal ? (
              <Button size="sm" variant="outline" onClick={() => regenerate(qc, message.conversation_id, message.id)}>
                Retry
              </Button>
            ) : null}
          </div>
        ) : null}

        {terminal ? (
          <div className={cn("flex items-center gap-1", !isLast && "md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100")}>
            <BranchNavigator message={message} disabled={busy} />
            <IconButton
              label={copied ? "Copied" : "Copy"}
              onClick={async () => {
                await navigator.clipboard.writeText(text);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
            >
              {copied ? <Check /> : <Copy />}
            </IconButton>
            {status === "completed" ? <ReadAloud message={message} text={text} /> : null}
            <IconButton label="Regenerate" disabled={busy} onClick={() => regenerate(qc, message.conversation_id, message.id)}>
              <RefreshCw />
            </IconButton>
            {status === "completed" ? (
              <>
                <IconButton label="Good response" aria-pressed={rating === "up"} className={cn(rating === "up" && "text-primary")} onClick={() => { setRating("up"); void sendFeedback(message.id, "up"); }}>
                  <ThumbsUp />
                </IconButton>
                <IconButton label="Bad response" aria-pressed={rating === "down"} className={cn(rating === "down" && "text-primary")} onClick={() => { setRating("down"); void sendFeedback(message.id, "down"); }}>
                  <ThumbsDown />
                </IconButton>
              </>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";

import type { Message } from "@/lib/types";

import { switchBranch } from "../actions";

export function BranchNavigator({ message, disabled }: { message: Message; disabled?: boolean }) {
  const qc = useQueryClient();
  const s = message.siblings;
  if (s.count < 2) return null;
  return (
    <div className="flex items-center gap-0.5 text-xs text-muted-foreground">
      <button
        type="button"
        className="rounded p-1 hover:bg-accent disabled:opacity-40"
        aria-label="Previous version"
        disabled={disabled || !s.prev_id}
        onClick={() => s.prev_id && switchBranch(qc, message.conversation_id, s.prev_id)}
      >
        <ChevronLeft className="size-4" />
      </button>
      <span aria-live="polite">
        {s.index + 1} / {s.count}
      </span>
      <button
        type="button"
        className="rounded p-1 hover:bg-accent disabled:opacity-40"
        aria-label="Next version"
        disabled={disabled || !s.next_id}
        onClick={() => s.next_id && switchBranch(qc, message.conversation_id, s.next_id)}
      >
        <ChevronRight className="size-4" />
      </button>
    </div>
  );
}

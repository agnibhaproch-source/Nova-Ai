"use client";

/**
 * Chat stream orchestration (docs/13 §10, docs/29 §6). Lives outside components so a stream
 * keeps running across route changes (/chat → /c/[id]).
 */
import type { QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, type ListEnvelope } from "@/lib/api/client";
import { ApiError, errorMessage } from "@/lib/api/errors";
import { postStream, resumeStream, type StreamEvent } from "@/lib/sse/stream-client";
import type { Citation, Message } from "@/lib/types";
import { uuid } from "@/lib/utils";
import { useStreamStore } from "@/stores/stream-store";

import { chatKeys } from "./api";

const active = new Set<string>(); // assistant ids with an attached client stream

function handler(qc: QueryClient, cid: string) {
  const store = useStreamStore.getState;
  return (ev: StreamEvent) => {
    const d = ev.data;
    switch (ev.event) {
      case "message_start":
      case "message_snapshot": {
        const assistant = (d.assistant_message ?? d.message) as Message;
        const existing = store().turns[assistant.id];
        const snapshotText = assistant.parts?.filter((p) => p.type === "text").map((p) => p.text).join("") ?? "";
        store().start({
          conversationId: cid,
          userMessage: (d.user_message as Message | null) ?? existing?.userMessage ?? null,
          assistant,
          text: ev.event === "message_snapshot" ? snapshotText : existing?.text ?? "",
          parts:
            ev.event === "message_snapshot"
              ? Object.fromEntries((assistant.parts ?? []).filter((p) => p.type !== "citation").map((p) => [p.position, p]))
              : existing?.parts ?? {},
          citations: existing?.citations ?? [],
          stopping: false,
          lastEventId: ev.id ?? existing?.lastEventId ?? 0,
          error: null,
        });
        active.add(assistant.id);
        break;
      }
      case "content_delta":
        store().append(
          String(d.message_id),
          String(d.delta ?? ""),
          typeof d.part_position === "number" ? d.part_position : null,
          ev.id,
        );
        break;
      case "tool_start":
        store().setPart(String(d.message_id), {
          position: Number(d.part_position),
          type: "tool_call",
          tool_name: d.tool_name,
          label: d.label,
          arguments: d.arguments,
          status: "running",
        });
        break;
      case "tool_result": {
        const id = String(d.message_id);
        const pos = Number(d.part_position);
        store().setPart(id, { position: pos - 1, type: "tool_call", status: d.status });
        const code = d.code as Record<string, unknown> | null;
        store().setPart(
          id,
          code
            ? { position: pos, type: "code", ...code, text: String(code.code ?? "") }
            : { position: pos, type: "tool_result", tool_name: d.tool_name, status: d.status, summary: d.summary, display: d.display },
        );
        break;
      }
      case "citation":
        store().addCitation(String(d.message_id), d.citation as Citation);
        break;
      case "usage":
        void qc.invalidateQueries({ queryKey: chatKeys.quota });
        break;
      case "conversation_updated":
        void qc.invalidateQueries({ queryKey: ["conversations"] });
        break;
      case "message_complete":
      case "error": {
        const id = String(d.message_id ?? "");
        if (ev.event === "error") {
          store().patch(id, {
            error: { code: String(d.code), message: String(d.message), retryable: Boolean(d.retryable) },
          });
        }
        void finalize(qc, cid, id);
        break;
      }
    }
  };
}

async function finalize(qc: QueryClient, cid: string, assistantId: string) {
  await qc.invalidateQueries({ queryKey: chatKeys.messages(cid) });
  active.delete(assistantId);
  useStreamStore.getState().remove(assistantId);
  setTimeout(() => void qc.invalidateQueries({ queryKey: ["conversations"] }), 1500);
  // Titles are generated asynchronously right after the first answer (docs/11 §5).
  setTimeout(() => void qc.invalidateQueries({ queryKey: ["conversations"] }), 4000);
  // Memory extraction runs in the worker after the answer (docs/17 §4); surface updates.
  setTimeout(() => void notifyMemory(qc), 5000);
}

async function notifyMemory(qc: QueryClient) {
  try {
    const { data } = await api<ListEnvelope<{ type: string }>>("/memories/notifications");
    if (data.some((n) => n.type === "memory_updated")) {
      toast("Memory updated", { action: { label: "Manage", onClick: () => window.location.assign("/settings/memory") } });
      void qc.invalidateQueries({ queryKey: ["memories"] });
    }
  } catch {
    /* non-critical */
  }
}

function reportError(err: unknown) {
  if (err instanceof ApiError && ["RATE_LIMITED", "QUOTA_EXCEEDED"].includes(err.code)) {
    toast.error(err.message, { duration: 6000 });
  } else toast.error(errorMessage(err));
}

export async function sendMessage(
  qc: QueryClient,
  cid: string,
  content: string,
  opts: {
    parentId?: string | null;
    modelKey?: string;
    fileIds?: string[];
    tools?: { web_search?: boolean; code_execution?: boolean };
    onError?: (err: unknown) => void;
  } = {},
): Promise<boolean> {
  useStreamStore.getState().setPendingUser({ conversationId: cid, content });
  try {
    await postStream(
      `/conversations/${cid}/messages`,
      {
        content,
        parent_message_id: opts.parentId ?? undefined,
        model_key: opts.modelKey,
        file_ids: opts.fileIds?.length ? opts.fileIds : undefined,
        tools: opts.tools,
      },
      handler(qc, cid),
      { idempotencyKey: uuid() },
    );
    return true;
  } catch (err) {
    useStreamStore.getState().setPendingUser(null);
    opts.onError?.(err);
    reportError(err);
    return false;
  }
}

export async function regenerate(qc: QueryClient, cid: string, messageId: string, modelKey?: string) {
  try {
    await postStream(`/messages/${messageId}/regenerate`, { model_key: modelKey }, handler(qc, cid));
  } catch (err) {
    reportError(err);
  }
}

export async function editMessage(qc: QueryClient, cid: string, messageId: string, content: string) {
  try {
    await postStream(`/messages/${messageId}/edit`, { content }, handler(qc, cid));
  } catch (err) {
    reportError(err);
  }
}

export async function stopGeneration(assistantId: string) {
  useStreamStore.getState().patch(assistantId, { stopping: true });
  try {
    await api(`/messages/${assistantId}/cancel`, { method: "POST" });
  } catch (err) {
    reportError(err);
  }
}

/** Attach to an in-progress generation after reload (docs/13 §7). */
export async function attach(qc: QueryClient, cid: string, assistantId: string) {
  if (active.has(assistantId)) return;
  active.add(assistantId);
  try {
    await resumeStream(assistantId, 0, handler(qc, cid));
  } catch {
    active.delete(assistantId);
    void qc.invalidateQueries({ queryKey: chatKeys.messages(cid) });
  }
}

export async function switchBranch(qc: QueryClient, cid: string, messageId: string) {
  try {
    await api(`/conversations/${cid}/branch`, { method: "POST", json: { message_id: messageId } });
    await qc.invalidateQueries({ queryKey: chatKeys.messages(cid) });
  } catch (err) {
    reportError(err);
  }
}

export async function sendFeedback(messageId: string, rating: "up" | "down", reasons: string[] = []) {
  try {
    await api(`/messages/${messageId}/feedback`, { method: "PUT", json: { rating, reasons } });
    toast.success("Thanks for the feedback");
  } catch (err) {
    reportError(err);
  }
}

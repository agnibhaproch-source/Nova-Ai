/** POST+stream and resume-with-Last-Event-ID client (docs/13 §5, §7). */
import { csrfToken } from "@/lib/api/client";
import { toApiError } from "@/lib/api/errors";

import { readSSE } from "./parser";

export type StreamEvent = { id: number | null; event: string; data: Record<string, unknown> };
export type OnEvent = (ev: StreamEvent) => void;

const TERMINAL = new Set(["message_complete", "error"]);
const BACKOFF_MS = [500, 1000, 2000, 4000, 8000, 8000];

async function consume(res: Response, onEvent: OnEvent): Promise<{ lastId: number; done: boolean }> {
  let lastId = 0;
  let done = false;
  if (!res.body) return { lastId, done };
  for await (const ev of readSSE(res.body)) {
    if (ev.id !== null && ev.id > 0) lastId = ev.id;
    let data: Record<string, unknown> = {};
    try {
      data = JSON.parse(ev.data) as Record<string, unknown>;
    } catch {
      continue;
    }
    onEvent({ id: ev.id, event: ev.event, data });
    if (TERMINAL.has(ev.event)) done = true;
  }
  return { lastId, done };
}

export async function resumeStream(
  messageId: string,
  lastEventId: number,
  onEvent: OnEvent,
  signal?: AbortSignal,
): Promise<void> {
  let last = lastEventId;
  for (let attempt = 0; attempt <= BACKOFF_MS.length; attempt++) {
    try {
      const res = await fetch(`/api/v1/messages/${messageId}/stream`, {
        headers: { accept: "text/event-stream", "last-event-id": String(last) },
        credentials: "same-origin",
        signal,
      });
      if (!res.ok) throw await toApiError(res);
      const { lastId, done } = await consume(res, (ev) => {
        if (ev.id !== null && ev.id > 0 && ev.id <= last) return; // dedupe replays
        onEvent(ev);
      });
      last = Math.max(last, lastId);
      if (done) return;
    } catch (err) {
      if (signal?.aborted) return;
      if (err && typeof err === "object" && "status" in err && (err as { status: number }).status < 500)
        throw err;
    }
    if (attempt < BACKOFF_MS.length) await new Promise((r) => setTimeout(r, BACKOFF_MS[attempt]));
  }
  throw new Error("CONNECTION_LOST");
}

/** POSTs a streaming request; on a dropped connection, resumes via GET .../stream. */
export async function postStream(
  path: string,
  body: unknown,
  onEvent: OnEvent,
  opts: { idempotencyKey?: string; signal?: AbortSignal } = {},
): Promise<void> {
  const headers: Record<string, string> = {
    accept: "text/event-stream",
    "content-type": "application/json",
    "x-csrf-token": csrfToken(),
  };
  if (opts.idempotencyKey) headers["idempotency-key"] = opts.idempotencyKey;
  const res = await fetch(`/api/v1${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    credentials: "same-origin",
    signal: opts.signal,
  });
  if (!res.ok) throw await toApiError(res);
  let messageId: string | null = null;
  let last = 0;
  try {
    const { lastId, done } = await consume(res, (ev) => {
      if (ev.event === "message_start") {
        const a = ev.data.assistant_message as { id: string } | undefined;
        messageId = a?.id ?? null;
      }
      onEvent(ev);
    });
    last = lastId;
    if (done) return;
  } catch {
    if (opts.signal?.aborted) return;
  }
  if (messageId) await resumeStream(messageId, last, onEvent, opts.signal);
}

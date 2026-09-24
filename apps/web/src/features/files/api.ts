"use client";

import { useQuery } from "@tanstack/react-query";

import { api, type Envelope, type ListEnvelope } from "@/lib/api/client";
import type { Capabilities, FileInfo } from "@/lib/types";

export const fileKeys = {
  all: ["files"] as const,
  one: (id: string) => ["files", id] as const,
  url: (id: string) => ["files", id, "url"] as const,
  caps: ["capabilities"] as const,
  tools: ["tools"] as const,
};

const PROCESSING = new Set(["pending_upload", "uploaded", "scanning", "processing"]);
export const isProcessing = (f: FileInfo) => PROCESSING.has(f.status);

export function useCapabilities() {
  return useQuery({
    queryKey: fileKeys.caps,
    staleTime: 5 * 60_000,
    queryFn: async () => (await api<Envelope<Capabilities>>("/capabilities")).data,
  });
}

export interface ToolInfo {
  name: string;
  display_name: string;
  description: string;
  enabled: boolean;
  disabled_reason: string | null;
  daily_limit: number | null;
}

export function useTools() {
  return useQuery({
    queryKey: fileKeys.tools,
    staleTime: 60_000,
    queryFn: async () => (await api<ListEnvelope<ToolInfo>>("/tools")).data,
  });
}

/** Polls a file until processing finishes (docs/18 §6). */
export function useFile(id: string, initial?: FileInfo) {
  return useQuery({
    queryKey: fileKeys.one(id),
    initialData: initial,
    queryFn: async () => (await api<Envelope<FileInfo>>(`/files/${id}`)).data,
    refetchInterval: (q) => (q.state.data && !isProcessing(q.state.data) ? false : 1500),
  });
}

/** Short-lived presigned URL for an image derivative. */
export function useImageUrl(id: string | null | undefined) {
  return useQuery({
    queryKey: fileKeys.url(id ?? ""),
    enabled: !!id,
    staleTime: 50 * 60_000,
    queryFn: async () => (await api<Envelope<{ url: string }>>(`/files/${id}/content-url`)).data.url,
  });
}

interface Initiated {
  file: FileInfo;
  upload: { url: string; fields: Record<string, string>; expires_at: string };
}

/** initiate → direct presigned POST to object storage (progress via XHR) → complete. */
export async function uploadFile(
  file: File,
  opts: { conversationId?: string | null; onProgress?: (pct: number) => void } = {},
): Promise<FileInfo> {
  const init = (
    await api<Envelope<Initiated>>("/files", {
      method: "POST",
      json: {
        filename: file.name,
        size_bytes: file.size,
        mime_type: guessMime(file),
        conversation_id: opts.conversationId ?? undefined,
      },
    })
  ).data;
  await new Promise<void>((resolve, reject) => {
    const form = new FormData();
    for (const [k, v] of Object.entries(init.upload.fields)) form.append(k, v);
    form.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", init.upload.url);
    xhr.upload.onprogress = (e) => e.lengthComputable && opts.onProgress?.(Math.round((e.loaded / e.total) * 100));
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error("Upload failed. Please try again.")));
    xhr.onerror = () => reject(new Error("Upload failed. Check your connection."));
    xhr.send(form);
  });
  return (await api<Envelope<FileInfo>>(`/files/${init.file.id}/complete`, { method: "POST" })).data;
}

const MIME: Record<string, string> = {
  md: "text/markdown",
  markdown: "text/markdown",
  csv: "text/csv",
  txt: "text/plain",
  pdf: "application/pdf",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
};

/** Browsers often report "" for .md/.csv; fall back to the extension. */
function guessMime(file: File) {
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  return file.type || MIME[ext] || "application/octet-stream";
}

export function formatBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

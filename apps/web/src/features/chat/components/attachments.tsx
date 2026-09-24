"use client";

import { useQueryClient } from "@tanstack/react-query";
import { FileText, Loader2, TriangleAlert, X } from "lucide-react";
import { useEffect } from "react";

import { fileKeys, formatBytes, isProcessing, useFile } from "@/features/files/api";
import type { FileInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface Pending {
  key: string;
  name: string;
  progress: number;
  file?: FileInfo;
  error?: string;
}

/** One attachment chip: upload progress, then server-side processing status (docs/18 §6). */
export function AttachmentChip({ item, onRemove, onReady }: { item: Pending; onRemove: () => void; onReady: (f: FileInfo) => void }) {
  const { data: file } = useFile(item.file?.id ?? "", item.file);
  const qc = useQueryClient();
  const f = item.file ? file : undefined;
  const failed = item.error || (f && ["failed", "rejected"].includes(f.status));
  const working = !failed && (!f || isProcessing(f));

  useEffect(() => {
    if (f && f.status === "ready") {
      onReady(f);
      void qc.invalidateQueries({ queryKey: fileKeys.all });
    }
  }, [f, onReady, qc]);

  const label = item.error
    ? item.error
    : !f
      ? `Uploading ${item.progress}%`
      : f.status === "ready"
        ? formatBytes(f.size_bytes)
        : failed
          ? (f.error_message ?? "Couldn't process this file")
          : `${f.stage ?? "Processing"}…`;
  return (
    <div className={cn("flex max-w-64 items-center gap-2 rounded-xl border border-border bg-surface px-2.5 py-1.5", failed && "border-destructive/40")}>
      {working ? <Loader2 className="size-4 shrink-0 animate-spin text-muted-foreground" /> : failed ? <TriangleAlert className="size-4 shrink-0 text-destructive" /> : <FileText className="size-4 shrink-0 text-muted-foreground" />}
      <div className="min-w-0">
        <p className="truncate text-xs font-medium">{item.name}</p>
        <p className={cn("truncate text-[11px] text-muted-foreground", failed && "text-destructive")}>{label}</p>
      </div>
      <button type="button" aria-label={`Remove ${item.name}`} onClick={onRemove} className="rounded p-0.5 text-muted-foreground hover:bg-accent">
        <X className="size-3.5" />
      </button>
    </div>
  );
}

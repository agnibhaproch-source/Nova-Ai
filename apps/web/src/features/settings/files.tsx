"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, ImageIcon, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { EmptyState } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { fileKeys, formatBytes } from "@/features/files/api";
import { api, type ListEnvelope } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { FileInfo } from "@/lib/types";

import { Section } from "./section";

const STATUS: Record<string, string> = { ready: "Ready", failed: "Failed", rejected: "Rejected" };

export function FilesSettings() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: fileKeys.all, queryFn: async () => (await api<ListEnvelope<FileInfo>>("/files?limit=100")).data });
  return (
    <Section title="Files" description="Documents and images you've uploaded. Deleting a file removes it from search and future answers.">
      {data?.length === 0 ? <EmptyState icon={FileText} title="No files yet" description="Attach files in a chat with the paperclip." /> : null}
      {data?.map((f) => (
        <div key={f.id} className="flex items-center gap-3 px-5 py-3">
          {f.kind === "image" ? <ImageIcon className="size-4 text-muted-foreground" /> : <FileText className="size-4 text-muted-foreground" />}
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{f.filename}</p>
            <p className="text-xs text-muted-foreground">
              {formatBytes(f.size_bytes)} · {STATUS[f.status] ?? "Processing"}
              {f.page_count ? ` · ${f.page_count} pages` : ""}
            </p>
          </div>
          <a className="text-sm text-primary hover:underline" href={`/api/v1/files/${f.id}/download`}>Download</a>
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Delete ${f.filename}`}
            onClick={async () => {
              try { await api(`/files/${f.id}`, { method: "DELETE" }); await qc.invalidateQueries({ queryKey: fileKeys.all }); toast.success("File deleted"); }
              catch (err) { toast.error(errorMessage(err)); }
            }}
          >
            <Trash2 className="size-4" />
          </Button>
        </div>
      ))}
    </Section>
  );
}

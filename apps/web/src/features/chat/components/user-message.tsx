"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Check, Copy, FileText, Pencil } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { messageText, type Message } from "@/lib/types";

import { editMessage } from "../actions";
import { BranchNavigator } from "./branch-navigator";
import { IconButton } from "./icon-button";
import { FileImage } from "./message-parts";

function Attachments({ message }: { message: Message }) {
  const files = message.parts.filter((p) => p.type === "image" || p.type === "file");
  if (!files.length) return null;
  return (
    <div className="flex max-w-[88%] flex-wrap justify-end gap-2">
      {files.map((p) =>
        p.type === "image" && p.file_id ? (
          <FileImage key={p.position} id={String(p.file_id)} alt={String(p.filename ?? "")} className="max-h-48 rounded-xl border border-border object-cover" />
        ) : (
          <span key={p.position} className="flex items-center gap-2 rounded-xl border border-border px-3 py-2 text-sm">
            <FileText className="size-4 text-muted-foreground" />
            <span className="max-w-48 truncate">{String(p.filename ?? "File")}</span>
          </span>
        ),
      )}
    </div>
  );
}

export function UserMessage({ message, busy }: { message: Message; busy: boolean }) {
  const qc = useQueryClient();
  const text = messageText(message);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(text);
  const [copied, setCopied] = useState(false);

  if (editing)
    return (
      <div className="ml-auto w-full max-w-[85%] space-y-2">
        <textarea
          autoFocus
          aria-label="Edit message"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") setEditing(false);
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              if (draft.trim()) {
                setEditing(false);
                void editMessage(qc, message.conversation_id, message.id, draft.trim());
              }
            }
          }}
          rows={Math.min(10, draft.split("\n").length + 1)}
          className="w-full resize-none rounded-2xl border border-primary/50 bg-user-bubble px-4 py-2.5 text-base outline-none"
        />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>Cancel</Button>
          <Button
            size="sm"
            disabled={!draft.trim() || busy}
            onClick={() => {
              setEditing(false);
              void editMessage(qc, message.conversation_id, message.id, draft.trim());
            }}
          >
            Send
          </Button>
        </div>
      </div>
    );

  return (
    <div className="group flex flex-col items-end gap-1">
      <Attachments message={message} />
      {text.trim() ? (
        <div className="max-w-[88%] whitespace-pre-wrap break-words rounded-[20px] rounded-br-md bg-user-bubble px-4 py-2.5 md:max-w-[80%]">
          {text}
        </div>
      ) : null}
      <div className="flex items-center gap-1 opacity-100 transition-opacity md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100">
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
        <IconButton label="Edit" disabled={busy} onClick={() => { setDraft(text); setEditing(true); }}>
          <Pencil />
        </IconButton>
      </div>
    </div>
  );
}

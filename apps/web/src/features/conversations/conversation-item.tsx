"use client";

import { Archive, MoreHorizontal, Pencil, Pin, PinOff, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Conversation } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useStreamStore } from "@/stores/stream-store";

import { useDeleteConversation, useRestoreConversation, useUpdateConversation } from "./api";

export function ConversationItem({ c, active, onNavigate }: { c: Conversation; active: boolean; onNavigate?: () => void }) {
  const router = useRouter();
  const update = useUpdateConversation();
  const del = useDeleteConversation();
  const restore = useRestoreConversation();
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(c.title);
  const generating = useStreamStore((s) => Object.values(s.turns).some((t) => t.conversationId === c.id));

  const commitRename = () => {
    setRenaming(false);
    const t = title.trim();
    if (t && t !== c.title) update.mutate({ id: c.id, patch: { title: t } });
    else setTitle(c.title);
  };

  if (renaming)
    return (
      <input
        autoFocus
        value={title}
        maxLength={200}
        onChange={(e) => setTitle(e.target.value)}
        onBlur={commitRename}
        onKeyDown={(e) => {
          if (e.key === "Enter") commitRename();
          if (e.key === "Escape") {
            setTitle(c.title);
            setRenaming(false);
          }
        }}
        className="h-9 w-full rounded-md border border-primary/50 bg-surface-raised px-2 text-sm outline-none"
        aria-label="Conversation title"
      />
    );

  return (
    <div className={cn("group relative flex h-9 items-center rounded-md hover:bg-accent", active && "bg-accent font-medium")}>
      <Link
        href={`/c/${c.id}`}
        onClick={onNavigate}
        aria-current={active ? "page" : undefined}
        className="flex h-full min-w-0 flex-1 items-center gap-2 px-2 text-sm"
      >
        <span className="truncate">{c.title}</span>
        {generating ? <span className="ml-auto size-1.5 shrink-0 animate-pulse rounded-full bg-primary" aria-label="Generating" /> : null}
      </Link>
      <DropdownMenu>
        <DropdownMenuTrigger
          aria-label={`Options for ${c.title}`}
          className="mr-1 rounded p-1 text-muted-foreground opacity-100 hover:bg-background data-[state=open]:opacity-100 md:opacity-0 md:group-hover:opacity-100 md:focus-visible:opacity-100"
        >
          <MoreHorizontal className="size-4" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuItem onSelect={() => setRenaming(true)}><Pencil /> Rename</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => update.mutate({ id: c.id, patch: { pinned: !c.pinned } })}>
            {c.pinned ? <PinOff /> : <Pin />} {c.pinned ? "Unpin" : "Pin"}
          </DropdownMenuItem>
          <DropdownMenuItem
            onSelect={() => {
              update.mutate({ id: c.id, patch: { archived: true } });
              toast("Conversation archived", {
                action: { label: "Undo", onClick: () => update.mutate({ id: c.id, patch: { archived: false } }) },
              });
            }}
          >
            <Archive /> Archive
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            destructive
            onSelect={async () => {
              await del.mutateAsync({ id: c.id });
              if (active) router.push("/chat");
              toast("Moved to trash", {
                description: "Restorable for 30 days.",
                action: { label: "Undo", onClick: () => restore.mutate(c.id) },
              });
            }}
          >
            <Trash2 /> Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

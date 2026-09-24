"use client";

import { MessageSquare } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef } from "react";

import { EmptyState, ErrorState } from "@/components/common/states";
import { Skeleton } from "@/components/ui/skeleton";

import { useConversations } from "./api";
import { ConversationItem } from "./conversation-item";
import { groupConversations } from "./group";

export function ConversationList({ onNavigate }: { onNavigate?: () => void }) {
  const params = useParams<{ conversationId?: string }>();
  const q = useConversations();
  const sentinel = useRef<HTMLDivElement>(null);
  const items = useMemo(() => q.data?.pages.flatMap((p) => p.data) ?? [], [q.data]);
  const groups = useMemo(() => groupConversations(items), [items]);

  useEffect(() => {
    const el = sentinel.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => e?.isIntersecting && q.hasNextPage && !q.isFetchingNextPage && void q.fetchNextPage(),
      { rootMargin: "400px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [q]);

  if (q.isLoading)
    return (
      <div className="space-y-2 px-2">
        {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-8 w-full" />)}
      </div>
    );
  if (q.error) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  if (!items.length) return <EmptyState icon={MessageSquare} title="No conversations yet" />;

  return (
    <nav aria-label="Conversations" className="space-y-4 px-2">
      {groups.map((g) => (
        <div key={g.label}>
          <p className="px-2 pb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">{g.label}</p>
          {g.items.map((c) => (
            <ConversationItem key={c.id} c={c} active={params.conversationId === c.id} onNavigate={onNavigate} />
          ))}
        </div>
      ))}
      <div ref={sentinel} className="h-1" />
    </nav>
  );
}

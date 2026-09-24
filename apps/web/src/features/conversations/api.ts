"use client";

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from "@tanstack/react-query";

import { api, type Envelope, type ListEnvelope } from "@/lib/api/client";
import type { Conversation } from "@/lib/types";

export const convKeys = {
  list: (archived = false, deleted = false) => ["conversations", { archived, deleted }] as const,
  one: (id: string) => ["conversation", id] as const,
};

export function useConversations(opts: { archived?: boolean; deleted?: boolean } = {}) {
  const archived = opts.archived ?? false;
  const deleted = opts.deleted ?? false;
  return useInfiniteQuery({
    queryKey: convKeys.list(archived, deleted),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const q = new URLSearchParams({ limit: "30", archived: String(archived), deleted: String(deleted) });
      if (pageParam) q.set("cursor", pageParam);
      return api<ListEnvelope<Conversation>>(`/conversations?${q}`);
    },
    getNextPageParam: (last) => last.page.next_cursor,
  });
}

export function useConversation(id: string | null) {
  return useQuery({
    queryKey: convKeys.one(id ?? ""),
    enabled: !!id,
    queryFn: async () => (await api<Envelope<Conversation>>(`/conversations/${id}`)).data,
  });
}

export function useCreateConversation() {
  return useMutation({
    mutationFn: async ({ modelKey, groqApiKey }: { modelKey?: string; groqApiKey?: string }) =>
      (
        await api<Envelope<Conversation>>("/conversations", {
          method: "POST",
          json: { model_key: modelKey, groq_api_key: groqApiKey },
        })
      ).data,
  });
}

type Patch = Partial<Pick<Conversation, "title" | "pinned" | "archived" | "model_key">>;

/** Optimistic rename/pin/archive with rollback (docs/29 §4). */
export function useUpdateConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, patch }: { id: string; patch: Patch }) =>
      (await api<Envelope<Conversation>>(`/conversations/${id}`, { method: "PATCH", json: patch })).data,
    onMutate: async ({ id, patch }) => {
      await qc.cancelQueries({ queryKey: ["conversations"] });
      const snapshot = qc.getQueriesData<InfiniteData<ListEnvelope<Conversation>>>({ queryKey: ["conversations"] });
      qc.setQueriesData<InfiniteData<ListEnvelope<Conversation>>>({ queryKey: ["conversations"] }, (data) =>
        data
          ? { ...data, pages: data.pages.map((p) => ({ ...p, data: p.data.map((c) => (c.id === id ? { ...c, ...patch } : c)) })) }
          : data,
      );
      return { snapshot };
    },
    onError: (_e, _v, ctx) => ctx?.snapshot.forEach(([k, v]) => qc.setQueryData(k, v)),
    onSettled: (_d, _e, { id }) => {
      void qc.invalidateQueries({ queryKey: ["conversations"] });
      void qc.invalidateQueries({ queryKey: convKeys.one(id) });
    },
  });
}

export function useDeleteConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, permanent = false }: { id: string; permanent?: boolean }) =>
      api<void>(`/conversations/${id}${permanent ? "?permanent=true" : ""}`, { method: "DELETE" }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["conversations"] }),
  });
}

export function useRestoreConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api(`/conversations/${id}/restore`, { method: "POST" }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["conversations"] }),
  });
}

export type SearchHit = {
  conversation_id: string;
  title: string;
  message_id: string | null;
  snippet: string | null;
  highlights: [number, number][];
  last_message_at: string;
};

export function useConversationSearch(q: string) {
  return useQuery({
    queryKey: ["conversation-search", q],
    enabled: q.trim().length > 0,
    staleTime: 10_000,
    queryFn: async () =>
      (await api<ListEnvelope<SearchHit>>(`/conversations/search?q=${encodeURIComponent(q.trim())}`)).data,
  });
}

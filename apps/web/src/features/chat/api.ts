"use client";

import { useQuery } from "@tanstack/react-query";

import { api, type Envelope, type ListEnvelope } from "@/lib/api/client";
import type { Message, ModelInfo, Preferences, Quota } from "@/lib/types";

export const chatKeys = {
  messages: (cid: string) => ["messages", cid] as const,
  models: ["models"] as const,
  quota: ["usage", "quota"] as const,
  prefs: ["preferences"] as const,
};

export type MessagesPage = ListEnvelope<Message> & {
  meta: { current_leaf_message_id: string | null; active_generation_message_id: string | null };
};

export function useMessages(cid: string | null) {
  return useQuery({
    queryKey: chatKeys.messages(cid ?? ""),
    enabled: !!cid,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    queryFn: () => api<MessagesPage>(`/conversations/${cid}/messages?limit=100`),
  });
}

export function useModels() {
  return useQuery({
    queryKey: chatKeys.models,
    staleTime: 10 * 60_000,
    queryFn: async () => (await api<ListEnvelope<ModelInfo>>("/models")).data,
  });
}

export function useQuota() {
  return useQuery({
    queryKey: chatKeys.quota,
    queryFn: async () => (await api<Envelope<Quota>>("/usage/quota")).data,
  });
}

export function usePreferences() {
  return useQuery({
    queryKey: chatKeys.prefs,
    staleTime: 5 * 60_000,
    queryFn: async () => (await api<Envelope<Preferences>>("/users/me/preferences")).data,
  });
}

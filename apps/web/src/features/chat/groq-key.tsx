"use client";

/**
 * BYOK: the user's Groq API key for a chat (docs/14 §2a). The key lives only in React state
 * until it's sent once to our API, which validates and keeps it encrypted server-side for that
 * conversation. It is never written to localStorage and never read back from the server.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, type Envelope } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";

export interface GroqKeyStatus {
  mode: "user" | "server";
  configured: boolean;
  expires_in_seconds: number | null;
}

export const groqKeyKeys = {
  config: ["app-config"] as const,
  status: (cid: string) => ["groq-key", cid] as const,
};

export function useKeyMode() {
  return useQuery({
    queryKey: groqKeyKeys.config,
    staleTime: 5 * 60_000,
    queryFn: async () =>
      (await api<Envelope<{ groq_key_mode?: "user" | "server" }>>("/app-config")).data.groq_key_mode ??
      "server",
  });
}

export function useGroqKeyStatus(cid: string | null) {
  const { data: mode } = useKeyMode();
  return useQuery({
    queryKey: groqKeyKeys.status(cid ?? ""),
    enabled: !!cid && mode === "user",
    queryFn: async () => (await api<Envelope<GroqKeyStatus>>(`/conversations/${cid}/groq-key`)).data,
  });
}

export function looksLikeGroqKey(v: string) {
  return /^gsk_\S{16,}$/.test(v.trim());
}

/** Controlled input for a new chat: the key is sent with the first message. */
export function NewChatKeyField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="mx-auto w-full max-w-3xl px-3 pb-2 md:px-6">
      <label className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2">
        <KeyRound className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        <span className="sr-only">Groq API key for this chat</span>
        <input
          type="password"
          autoComplete="off"
          spellCheck={false}
          placeholder="Paste your Groq API key (gsk_…) to start this chat"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        />
      </label>
    </div>
  );
}

/** Existing chat whose key expired or was removed: re-enter it to continue. */
export function ReenterKeyBar({ cid }: { cid: string }) {
  const qc = useQueryClient();
  const [value, setValue] = useState("");
  const save = useMutation({
    mutationFn: async () =>
      (
        await api<Envelope<GroqKeyStatus>>(`/conversations/${cid}/groq-key`, {
          method: "PUT",
          json: { api_key: value.trim() },
        })
      ).data,
    onSuccess: (d) => {
      setValue("");
      qc.setQueryData(groqKeyKeys.status(cid), d);
    },
  });
  return (
    <form
      className="mx-auto w-full max-w-3xl px-3 pb-2 md:px-6"
      onSubmit={(e) => {
        e.preventDefault();
        if (looksLikeGroqKey(value)) save.mutate();
      }}
    >
      <p className="mb-1 px-1 text-sm">This chat needs your Groq API key to continue.</p>
      <div className="flex gap-2">
        <Input
          type="password"
          autoComplete="off"
          spellCheck={false}
          aria-label="Groq API key"
          placeholder="gsk_…"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <Button type="submit" disabled={!looksLikeGroqKey(value) || save.isPending}>
          {save.isPending ? "Checking…" : "Use key"}
        </Button>
      </div>
      {save.error ? <p className="mt-1 px-1 text-xs text-destructive">{errorMessage(save.error)}</p> : null}
    </form>
  );
}

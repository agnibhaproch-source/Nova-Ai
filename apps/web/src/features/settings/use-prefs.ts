"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { chatKeys } from "@/features/chat/api";
import { api, type Envelope } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { Preferences } from "@/lib/types";

/** Optimistic preference updates with rollback (docs/27 §11). */
export function useUpdatePreferences() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (patch: Partial<Preferences>) =>
      (await api<Envelope<Preferences>>("/users/me/preferences", { method: "PATCH", json: patch })).data,
    onMutate: async (patch) => {
      await qc.cancelQueries({ queryKey: chatKeys.prefs });
      const prev = qc.getQueryData<Preferences>(chatKeys.prefs);
      if (prev) qc.setQueryData(chatKeys.prefs, { ...prev, ...patch });
      return { prev };
    },
    onError: (err, _p, ctx) => {
      if (ctx?.prev) qc.setQueryData(chatKeys.prefs, ctx.prev);
      toast.error(errorMessage(err));
    },
    onSuccess: (data) => qc.setQueryData(chatKeys.prefs, data),
  });
}

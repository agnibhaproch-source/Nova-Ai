"use client";

import { useState } from "react";

import { TopBar } from "@/components/layout/top-bar";
import { useConversation, useUpdateConversation } from "@/features/conversations/api";
import { useUser } from "@/features/user/user-context";

import { usePreferences } from "../api";
import { ChatView } from "./chat-view";
import { ModelSelector } from "./model-selector";

export function ChatPage({ conversationId }: { conversationId: string | null }) {
  const user = useUser();
  const { data: conv } = useConversation(conversationId);
  const { data: prefs } = usePreferences();
  const update = useUpdateConversation();
  const [newModel, setNewModel] = useState<string | null>(null);
  const model = conversationId ? conv?.model_key ?? null : newModel ?? prefs?.default_model_key ?? null;

  return (
    <>
      <TopBar>
        <ModelSelector
          value={model}
          onChange={(k) =>
            conversationId ? update.mutate({ id: conversationId, patch: { model_key: k } }) : setNewModel(k)
          }
        />
        {conv ? <span className="hidden truncate text-sm text-muted-foreground md:inline">· {conv.title}</span> : null}
      </TopBar>
      <ChatView conversationId={conversationId} userName={user.display_name} modelKey={model} />
    </>
  );
}

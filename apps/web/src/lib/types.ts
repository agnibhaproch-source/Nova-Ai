/** Domain types mirroring docs/31 + docs/12 §9 response shapes. */

export type Role = "user" | "support" | "admin";

export interface User {
  id: string;
  email: string;
  display_name: string;
  avatar_url: string | null;
  role: Role;
  plan_key: "free" | "plus" | "pro";
  onboarding_completed: boolean;
  created_at: string;
}

export interface Preferences {
  theme: "system" | "light" | "dark";
  default_model_key: string | null;
  custom_instructions: string | null;
  about_user: string | null;
  memory_enabled: boolean;
  web_search_enabled: boolean;
  code_execution_enabled: boolean;
  send_with_enter: boolean;
  locale: string;
  timezone: string;
  tts_voice: string | null;
  analytics_opt_out: boolean;
}

export interface Conversation {
  id: string;
  title: string;
  title_source: "default" | "generated" | "user";
  model_key: string;
  pinned: boolean;
  archived: boolean;
  deleted_at: string | null;
  purge_at: string | null;
  current_leaf_message_id: string | null;
  last_message_at: string;
  created_at: string;
  message_count: number;
}

export type MessageStatus = "pending" | "streaming" | "completed" | "cancelled" | "failed";

export interface MessagePart {
  id?: string;
  position: number;
  type: "text" | "image" | "file" | "citation" | "tool_call" | "tool_result" | "code";
  text?: string;
  [k: string]: unknown;
}

export interface Citation {
  index: number;
  source_type: "file" | "web";
  file_id?: string | null;
  filename?: string | null;
  page_number?: number | null;
  sheet_name?: string | null;
  section_title?: string | null;
  snippet?: string | null;
  url?: string | null;
  title?: string | null;
  site_name?: string | null;
}

export interface FileInfo {
  id: string;
  filename: string;
  extension: string;
  mime_type: string;
  size_bytes: number;
  kind: "document" | "image";
  purpose: string;
  status: "pending_upload" | "uploaded" | "scanning" | "processing" | "ready" | "failed" | "rejected" | "deleted";
  stage: string | null;
  progress: number | null;
  indexed: boolean;
  error_code: string | null;
  error_message: string | null;
  page_count: number | null;
  chunk_count: number;
  created_at: string;
}

export interface Capabilities {
  vision: { enabled: boolean; model_keys: string[]; max_images_per_message: number };
  documents: { enabled: boolean; semantic_search: boolean; extensions: string[] };
  voice_input: { enabled: boolean };
  voice_output: { enabled: boolean; mode: "groq" | "browser" | "none"; voices: string[] };
  web_search: { enabled: boolean };
  code_execution: { enabled: boolean };
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  status: MessageStatus;
  parent_message_id: string | null;
  created_at: string;
  completed_at: string | null;
  model_key: string | null;
  finish_reason: string | null;
  error: { code: string; message: string } | null;
  parts: MessagePart[];
  siblings: { index: number; count: number; prev_id: string | null; next_id: string | null };
  feedback: { rating: "up" | "down"; reasons: string[]; comment: string | null } | null;
  usage: { prompt_tokens: number; completion_tokens: number; latency_ms: number | null } | null;
}

export interface ModelInfo {
  key: string;
  display_name: string;
  description: string;
  capabilities: { tools: boolean; vision: boolean; json: boolean };
  context_window: number | null;
  is_default: boolean;
  locked: boolean;
  required_plan: string | null;
}

export interface Quota {
  plan_key: string;
  period_resets: { daily_at: string; monthly_at: string };
  limits: Record<string, unknown>;
  used: { messages_today: number; tokens_month: number };
  messages_remaining_today: number;
  tokens_remaining_month: number;
}

export function citationsOf(m: Pick<Message, "parts">): Citation[] {
  return m.parts.filter((p) => p.type === "citation") as unknown as Citation[];
}

export function messageText(m: Pick<Message, "parts">): string {
  return m.parts
    .filter((p) => p.type === "text")
    .map((p) => p.text ?? "")
    .join("\n\n");
}

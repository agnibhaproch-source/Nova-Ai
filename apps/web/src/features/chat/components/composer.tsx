"use client";

import { ArrowUp, Camera, Code2, Globe, Loader2, Paperclip, Settings2, Square } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { DropdownMenu, DropdownMenuContent, DropdownMenuLabel, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import { uploadFile, useCapabilities } from "@/features/files/api";
import { captureScreen } from "@/features/quick-chat/capture";
import { useQuickChat } from "@/features/quick-chat/store";
import { errorMessage } from "@/lib/api/errors";
import type { FileInfo } from "@/lib/types";
import { cn, uuid } from "@/lib/utils";

import { usePreferences, useQuota } from "../api";
import { AttachmentChip, type Pending } from "./attachments";
import { DictateButton } from "./voice";

export interface SendExtras {
  fileIds: string[];
  tools: { web_search?: boolean; code_execution?: boolean };
}

interface Props {
  draftKey: string;
  busy: boolean;
  conversationId?: string | null;
  compact?: boolean;
  placeholder?: string;
  onSend: (text: string, extras: SendExtras) => Promise<boolean> | boolean;
  onStop: () => void;
  autoFocus?: boolean;
  /** Receives this composer's "attach these files" function (the chat view's drop zone uses it). */
  attachRef?: React.RefObject<((files: File[]) => void) | null>;
}

const DRAFT_PREFIX = "nova-draft:";

function loadDraft(key: string): string {
  try {
    return localStorage.getItem(DRAFT_PREFIX + key) ?? "";
  } catch {
    return "";
  }
}

function saveDraft(key: string, value: string) {
  try {
    if (value) localStorage.setItem(DRAFT_PREFIX + key, value);
    else localStorage.removeItem(DRAFT_PREFIX + key);
  } catch {
    /* storage unavailable */
  }
}

const MAX_ATTACHMENTS = 10;

export function Composer({ draftKey, busy, conversationId, compact, placeholder, onSend, onStop, autoFocus, attachRef }: Props) {
  const [text, setText] = useState(() => loadDraft(draftKey));
  const ref = useRef<HTMLTextAreaElement>(null);
  const { data: prefs } = usePreferences();
  const { data: quota } = useQuota();
  const sendWithEnter = prefs?.send_with_enter ?? true;
  const { data: caps } = useCapabilities();
  const [pending, setPending] = useState<Pending[]>([]);
  const [ready, setReady] = useState<Record<string, FileInfo>>({});
  const [tools, setTools] = useState<SendExtras["tools"]>({});
  const fileInput = useRef<HTMLInputElement>(null);
  const uploading = pending.some((p) => !p.error && !ready[p.key]);
  const accept = [...(caps?.documents.extensions ?? []), ...(caps?.vision.enabled ? ["png", "jpg", "jpeg", "webp", "gif"] : [])]
    .map((e) => `.${e}`)
    .join(",");

  const maxImages = caps?.vision.max_images_per_message ?? 3;
  const addFiles = (files: FileList | File[]) => {
    let list = Array.from(files).slice(0, MAX_ATTACHMENTS - pending.length);
    const images = pending.filter((p) => /\.(png|jpe?g|webp|gif)$/i.test(p.name)).length;
    const incoming = list.filter((f) => f.type.startsWith("image/"));
    if (images + incoming.length > maxImages) {
      toast.error(`Up to ${maxImages} images or screenshots per message.`);
      const room = Math.max(0, maxImages - images);
      const keep = new Set(incoming.slice(0, room));
      list = list.filter((f) => !f.type.startsWith("image/") || keep.has(f));
    }
    for (const file of list) {
      const key = uuid();
      setPending((p) => [...p, { key, name: file.name, progress: 0 }]);
      const patch = (x: Partial<Pending>) => setPending((p) => p.map((i) => (i.key === key ? { ...i, ...x } : i)));
      uploadFile(file, { conversationId, onProgress: (progress) => patch({ progress }) })
        .then((f) => patch({ file: f }))
        .catch((err: unknown) => patch({ error: errorMessage(err) }));
    }
  };
  // Screenshots taken with "\" (or by the desktop app) while Quick Chat was closed.
  const addFilesRef = useRef(addFiles);
  useEffect(() => {
    addFilesRef.current = addFiles;
  });
  // Files dropped anywhere on the chat view (images always; documents when enabled).
  const canAttach = !!(caps?.documents.enabled || caps?.vision.enabled);
  useEffect(() => {
    if (!attachRef) return;
    attachRef.current = canAttach ? (files) => addFilesRef.current(files) : null;
    return () => {
      attachRef.current = null;
    };
  }, [attachRef, canAttach]);
  useEffect(() => {
    if (!compact) return;
    const drain = () => {
      const shots = useQuickChat.getState().takeShots();
      if (shots.length) addFilesRef.current(shots);
    };
    queueMicrotask(drain); // screenshots queued before this composer mounted
    return useQuickChat.subscribe((st, prev) => {
      if (st.shots.length > prev.shots.length) drain();
    });
  }, [compact]);
  const [shooting, setShooting] = useState(false);
  const screenshot = async () => {
    setShooting(true);
    try {
      addFiles([await captureScreen()]);
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "NotAllowedError")) toast.error(errorMessage(err));
    } finally {
      setShooting(false);
    }
  };
  const markReady = useCallback((key: string, f: FileInfo) => setReady((r) => (r[key] ? r : { ...r, [key]: f })), []);
  const removeFile = (key: string) => {
    setPending((p) => p.filter((i) => i.key !== key));
    setReady((r) => {
      const next = { ...r };
      delete next[key];
      return next;
    });
  };

  useEffect(() => saveDraft(draftKey, text), [draftKey, text]);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
  }, [text]);

  // "/" opens Quick Chat (features/quick-chat); Esc stops generation (docs/27 §17).

  const readyIds = pending.map((p) => ready[p.key]?.id).filter((x): x is string => !!x);
  const submit = async () => {
    const value = text.trim();
    const fileIds = readyIds;
    // Text, attachments (e.g. just a screenshot), or both.
    if ((!value && !fileIds.length) || busy || uploading) return;
    setText("");
    const ok = await onSend(value, { fileIds, tools });
    if (!ok) setText(value);
    else {
      setPending([]);
      setReady({});
    }
  };
  const canSend = (!!text.trim() || readyIds.length > 0) && !uploading;

  const remaining = quota?.messages_remaining_today;
  return (
    <div className={cn("mx-auto w-full max-w-3xl", compact ? "px-0 pb-0" : "px-2 pb-[max(8px,env(safe-area-inset-bottom))] md:px-4 md:pb-4")}>
      <div
        className="rounded-[20px] border border-border bg-surface-raised p-2 shadow-composer transition-[border-color,box-shadow] focus-within:border-primary/40 focus-within:ring-2 focus-within:ring-primary/15 md:rounded-xl md:p-3">
        {pending.length ? (
          <div className="flex flex-wrap gap-2 px-1 pb-2">
            {pending.map((item) => (
              <AttachmentChip key={item.key} item={item} onRemove={() => removeFile(item.key)} onReady={(f) => markReady(item.key, f)} />
            ))}
          </div>
        ) : null}
        <textarea
          ref={ref}
          value={text}
          autoFocus={autoFocus}
          rows={1}
          placeholder={placeholder ?? "Message Nova…"}
          data-quick-chat-trigger={compact ? undefined : "empty"}
          onPaste={(e) => {
            const files = Array.from(e.clipboardData.files);
            if (files.length && canAttach) {
              e.preventDefault();
              addFiles(files);
            }
          }}
          aria-label="Message Nova"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape" && busy) {
              e.preventDefault();
              onStop();
              return;
            }
            if (e.key !== "Enter" || e.nativeEvent.isComposing) return;
            const send = sendWithEnter ? !e.shiftKey : e.metaKey || e.ctrlKey;
            if (send) {
              e.preventDefault();
              void submit();
            }
          }}
          className="max-h-60 min-h-6 w-full resize-none bg-transparent px-2 py-1 text-base outline-none placeholder:text-muted-foreground"
        />
        <div className="flex items-center gap-1 pt-1">
          {caps?.documents.enabled ? (
            <>
              <input ref={fileInput} type="file" multiple hidden accept={accept} onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }} />
              <button type="button" aria-label="Attach files" onClick={() => fileInput.current?.click()} className="flex size-8 items-center justify-center rounded-full text-muted-foreground hover:bg-accent">
                <Paperclip className="size-4" />
              </button>
            </>
          ) : null}
          {caps?.vision.enabled ? (
            <button
              type="button"
              aria-label="Take a screenshot"
              title="Screenshot the screen (\\)"
              onClick={() => void screenshot()}
              disabled={shooting}
              className="flex size-8 items-center justify-center rounded-full text-muted-foreground hover:bg-accent"
            >
              {shooting ? <Loader2 className="size-4 animate-spin" /> : <Camera className="size-4" />}
            </button>
          ) : null}
          {caps?.web_search.enabled || caps?.code_execution.enabled ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button type="button" aria-label="Tools" className="flex size-8 items-center justify-center rounded-full text-muted-foreground hover:bg-accent">
                  <Settings2 className="size-4" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-64 p-2">
                <DropdownMenuLabel>Tools for this message</DropdownMenuLabel>
                {caps.web_search.enabled ? (
                  <ToolToggle icon={<Globe className="size-4" />} label="Web search" checked={tools.web_search !== false} onChange={(v) => setTools((t) => ({ ...t, web_search: v }))} />
                ) : null}
                {caps.code_execution.enabled ? (
                  <ToolToggle icon={<Code2 className="size-4" />} label="Run Python" checked={tools.code_execution !== false} onChange={(v) => setTools((t) => ({ ...t, code_execution: v }))} />
                ) : null}
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
          <div className="flex-1" />
          <DictateButton onText={(t) => setText((cur) => (cur ? `${cur} ${t}` : t))} />
          {busy ? (
            <button
              type="button"
              onClick={onStop}
              aria-label="Stop generating"
              className="flex size-8 items-center justify-center rounded-full bg-foreground text-background"
            >
              <Square className="size-3.5 fill-current" />
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void submit()}
              disabled={!canSend}
              aria-label="Send message"
              className={cn(
                "flex size-8 items-center justify-center rounded-full bg-primary text-primary-foreground transition-opacity",
                !canSend && "opacity-40",
              )}
            >
              <ArrowUp className="size-4" />
            </button>
          )}
        </div>
      </div>
      <p className={cn("mt-2 text-center text-xs text-muted-foreground", compact && "hidden")}>
        {remaining !== undefined && remaining <= 5
          ? `${remaining} message${remaining === 1 ? "" : "s"} left today on ${quota?.plan_key ?? "your plan"}.`
          : "Nova can make mistakes. Verify important info."}
      </p>
    </div>
  );
}

function ToolToggle({ icon, label, checked, onChange }: { icon: React.ReactNode; label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm hover:bg-accent">
      {icon}
      <span className="flex-1">{label}</span>
      <Switch checked={checked} onCheckedChange={onChange} aria-label={label} />
    </label>
  );
}

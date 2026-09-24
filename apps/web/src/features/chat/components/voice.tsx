"use client";

import { Loader2, Mic, Square, Volume2 } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { useCapabilities } from "@/features/files/api";
import { csrfToken, type Envelope } from "@/lib/api/client";
import { errorMessage, toApiError } from "@/lib/api/errors";
import type { Message } from "@/lib/types";

import { IconButton } from "./icon-button";

/** Read aloud: Groq TTS through the API when configured, else the browser's speech engine. */
export function ReadAloud({ message, text }: { message: Message; text: string }) {
  const { data: caps } = useCapabilities();
  const [state, setState] = useState<"idle" | "loading" | "playing">("idle");
  const audio = useRef<HTMLAudioElement | null>(null);
  const mode = caps?.voice_output.mode ?? "browser";
  if (mode === "none" || !text) return null;

  const stop = () => {
    audio.current?.pause();
    if (typeof window !== "undefined") window.speechSynthesis?.cancel();
    setState("idle");
  };

  const play = async () => {
    if (mode === "browser") {
      if (!("speechSynthesis" in window)) return toast.error("Read aloud isn't supported in this browser.");
      const u = new SpeechSynthesisUtterance(text.replace(/[`*_#>|[\]]/g, ""));
      u.onend = () => setState("idle");
      window.speechSynthesis.speak(u);
      setState("playing");
      return;
    }
    setState("loading");
    try {
      const res = await fetch("/api/v1/voice/speech", {
        method: "POST",
        headers: { "content-type": "application/json", "x-csrf-token": csrfToken() },
        body: JSON.stringify({ message_id: message.id }),
      });
      if (!res.ok) throw await toApiError(res);
      const el = new Audio(URL.createObjectURL(await res.blob()));
      el.onended = () => setState("idle");
      audio.current = el;
      await el.play();
      setState("playing");
    } catch (err) {
      setState("idle");
      toast.error(errorMessage(err));
    }
  };

  return (
    <IconButton label={state === "playing" ? "Stop reading" : "Read aloud"} onClick={() => (state === "playing" ? stop() : void play())}>
      {state === "loading" ? <Loader2 className="animate-spin" /> : state === "playing" ? <Square /> : <Volume2 />}
    </IconButton>
  );
}

/** Dictation: records with MediaRecorder and transcribes via Groq STT (server-side). */
export function DictateButton({ onText }: { onText: (t: string) => void }) {
  const { data: caps } = useCapabilities();
  const [state, setState] = useState<"idle" | "recording" | "sending">("idle");
  const rec = useRef<MediaRecorder | null>(null);
  if (!caps?.voice_input.enabled) return null;

  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks: Blob[] = [];
      const r = new MediaRecorder(stream);
      r.ondataavailable = (e) => chunks.push(e.data);
      r.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setState("sending");
        try {
          const form = new FormData();
          form.append("audio", new Blob(chunks, { type: r.mimeType }), "dictation.webm");
          const res = await fetch("/api/v1/voice/transcriptions", {
            method: "POST",
            headers: { "x-csrf-token": csrfToken() },
            body: form,
          });
          if (!res.ok) throw await toApiError(res);
          const { data } = (await res.json()) as Envelope<{ text: string }>;
          onText(data.text);
        } catch (err) {
          toast.error(errorMessage(err));
        } finally {
          setState("idle");
        }
      };
      r.start();
      rec.current = r;
      setState("recording");
    } catch {
      toast.error("Microphone access was blocked.");
    }
  };

  return (
    <button
      type="button"
      aria-label={state === "recording" ? "Stop dictation" : "Dictate"}
      onClick={() => (state === "recording" ? rec.current?.stop() : void start())}
      disabled={state === "sending"}
      className={`flex size-8 items-center justify-center rounded-full hover:bg-accent ${state === "recording" ? "text-destructive" : "text-muted-foreground"}`}
    >
      {state === "sending" ? <Loader2 className="size-4 animate-spin" /> : state === "recording" ? <Square className="size-4" /> : <Mic className="size-4" />}
    </button>
  );
}


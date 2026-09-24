"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

const USE_CASES = ["Writing", "Coding", "Research", "Studying", "Work documents", "Other"];

export function Onboarding() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [cases, setCases] = useState<string[]>([]);
  const [instructions, setInstructions] = useState("");
  const [memory, setMemory] = useState(true);
  const [busy, setBusy] = useState(false);

  const finish = async (skipped: boolean) => {
    setBusy(true);
    try {
      await api("/users/me/onboarding/complete", {
        method: "POST",
        json: skipped ? {} : { custom_instructions: instructions.trim() || null, memory_enabled: memory },
      });
      void api("/analytics/events", {
        method: "POST",
        json: { events: [{ name: "onboarding_completed", properties: { use_cases: cases, memory_enabled: memory, skipped } }] },
      }).catch(() => undefined);
      router.replace("/chat");
      router.refresh();
    } catch (err) {
      toast.error(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-[560px] space-y-6 rounded-xl border border-border bg-surface-raised p-6 md:p-8">
      <div className="flex justify-center gap-2" aria-label={`Step ${step + 1} of 2`}>
        {[0, 1].map((i) => <span key={i} className={cn("size-2 rounded-full", i === step ? "bg-primary" : "bg-border")} />)}
      </div>
      {step === 0 ? (
        <div className="space-y-4">
          <h1 className="text-2xl font-semibold">What will you use Nova for?</h1>
          <div className="flex flex-wrap gap-2">
            {USE_CASES.map((c) => {
              const on = cases.includes(c);
              return (
                <button key={c} type="button" aria-pressed={on} onClick={() => setCases(on ? cases.filter((x) => x !== c) : [...cases, c])}
                  className={cn("rounded-full border px-3 py-1.5 text-sm", on ? "border-primary bg-accent text-primary" : "border-border hover:bg-accent")}>
                  {c}
                </button>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <h1 className="text-2xl font-semibold">Personalize Nova</h1>
          <label className="block space-y-1.5">
            <span className="text-sm font-medium">How should Nova respond? (optional)</span>
            <Textarea rows={4} maxLength={1500} value={instructions} onChange={(e) => setInstructions(e.target.value)}
              placeholder="e.g. Be concise. Prefer TypeScript examples. Explain like I'm a student." />
          </label>
          <div className="flex items-start justify-between gap-4 rounded-lg border border-border p-3">
            <div>
              <p className="text-sm font-medium">Memory</p>
              <p className="text-xs text-muted-foreground">Let Nova remember stable preferences you share. You can review or delete them anytime.</p>
            </div>
            <Switch checked={memory} onCheckedChange={setMemory} aria-label="Enable memory" />
          </div>
        </div>
      )}
      <div className="flex justify-between">
        <Button variant="ghost" onClick={() => finish(true)} disabled={busy}>Skip</Button>
        {step === 0 ? <Button onClick={() => setStep(1)}>Continue</Button> : <Button loading={busy} onClick={() => finish(false)}>Start chatting</Button>}
      </div>
    </div>
  );
}

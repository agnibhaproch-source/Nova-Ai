"use client";

import { Check, ChevronDown, Lock } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import { useModels } from "../api";

export function ModelSelector({ value, onChange }: { value: string | null; onChange: (k: string) => void }) {
  const { data: models } = useModels();
  const current = models?.find((m) => m.key === value) ?? models?.find((m) => m.is_default);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex items-center gap-1 rounded-md px-2 py-1.5 text-sm font-medium hover:bg-accent">
        {current?.display_name ?? "Model"}
        <ChevronDown className="size-4 text-muted-foreground" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-72">
        <DropdownMenuLabel>Model</DropdownMenuLabel>
        {models?.map((m) => (
          <DropdownMenuItem key={m.key} disabled={m.locked} onSelect={() => !m.locked && onChange(m.key)} className="items-start">
            <div className="flex-1">
              <div className="flex items-center gap-2 font-medium">
                {m.display_name}
                {m.locked ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-accent px-1.5 text-[10px] uppercase text-primary">
                    <Lock className="size-3" /> {m.required_plan}
                  </span>
                ) : null}
              </div>
              <p className="text-xs text-muted-foreground">{m.description}</p>
            </div>
            {m.key === current?.key ? <Check className="mt-0.5 text-primary" /> : null}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

export const SECTIONS = [
  ["general", "General"],
  ["profile", "Profile"],
  ["personalization", "Personalization"],
  ["memory", "Memory"],
  ["files", "Files"],
  ["data", "Data controls"],
  ["security", "Security"],
  ["usage", "Usage"],
  ["billing", "Billing"],
  ["api-keys", "API keys"],
] as const;

export function SettingsNav() {
  const path = usePathname();
  return (
    <nav aria-label="Settings" className="-mx-4 flex gap-1 overflow-x-auto px-4 md:mx-0 md:w-[220px] md:shrink-0 md:flex-col md:px-0">
      {SECTIONS.map(([key, label]) => {
        const href = `/settings/${key}`;
        const active = path === href;
        return (
          <Link key={key} href={href} aria-current={active ? "page" : undefined}
            className={cn("whitespace-nowrap rounded-md px-3 py-2 text-sm hover:bg-accent", active && "bg-accent font-medium")}>
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

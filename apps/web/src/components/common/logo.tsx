import { cn } from "@/lib/utils";

/** Original NOVA mark: four-point spark (docs/27 §1.5). */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-7", className)} aria-hidden>
      <defs>
        <linearGradient id="nova-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="oklch(0.55 0.2 275)" />
          <stop offset="1" stopColor="oklch(0.62 0.18 300)" />
        </linearGradient>
      </defs>
      <path
        d="M16 2c1.2 7.3 6.7 12.8 14 14-7.3 1.2-12.8 6.7-14 14-1.2-7.3-6.7-12.8-14-14 7.3-1.2 12.8-6.7 14-14z"
        fill="url(#nova-g)"
      />
    </svg>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 font-semibold tracking-tight", className)}>
      <LogoMark className="size-6" />
      NOVA AI
    </span>
  );
}

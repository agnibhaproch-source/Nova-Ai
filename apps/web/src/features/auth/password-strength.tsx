import { cn } from "@/lib/utils";

/** Lightweight client-side hint only; the server policy is authoritative (docs/09 §2). */
export function passwordScore(pw: string): number {
  if (pw.length < 12) return pw.length >= 8 ? 1 : 0;
  let s = 2;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) s++;
  if (/\d/.test(pw) && /[^A-Za-z0-9]/.test(pw)) s++;
  return Math.min(4, s);
}

export function PasswordStrength({ value }: { value: string }) {
  const score = passwordScore(value);
  const labels = ["Too short", "Weak", "Okay", "Good", "Strong"];
  return (
    <div className="space-y-1" aria-live="polite">
      <div className="flex gap-1">
        {[1, 2, 3, 4].map((i) => (
          <span
            key={i}
            className={cn(
              "h-1 flex-1 rounded-full bg-border transition-colors",
              score >= i && (score <= 1 ? "bg-destructive" : score === 2 ? "bg-warning" : "bg-success"),
            )}
          />
        ))}
      </div>
      <p className="text-xs text-muted-foreground">{value ? labels[score] : "At least 12 characters"}</p>
    </div>
  );
}

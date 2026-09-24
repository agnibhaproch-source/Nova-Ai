import * as React from "react";

import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-10 w-full rounded-md border border-border bg-surface-raised px-3 text-base outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-primary aria-invalid:border-destructive disabled:opacity-50 md:text-sm",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

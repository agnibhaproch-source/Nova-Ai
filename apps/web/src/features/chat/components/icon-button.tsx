import * as React from "react";

import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export function IconButton({
  label,
  className,
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <Tooltip label={label}>
      <button
        type="button"
        aria-label={label}
        className={cn(
          "inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-40 pointer-coarse:size-11 [&_svg]:size-4",
          className,
        )}
        {...props}
      >
        {children}
      </button>
    </Tooltip>
  );
}

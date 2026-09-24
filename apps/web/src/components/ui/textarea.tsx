import * as React from "react";

import { cn } from "@/lib/utils";

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      "w-full rounded-md border border-border bg-surface-raised px-3 py-2 text-base outline-none placeholder:text-muted-foreground focus-visible:border-primary md:text-sm",
      className,
    )}
    {...props}
  />
));
Textarea.displayName = "Textarea";

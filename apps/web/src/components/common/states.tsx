import type { LucideIcon } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { ApiError, errorMessage } from "@/lib/api/errors";

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
      {Icon ? <Icon className="size-8 text-muted-foreground" /> : null}
      <p className="font-semibold">{title}</p>
      {description ? <p className="max-w-sm text-sm text-muted-foreground">{description}</p> : null}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const requestId = error instanceof ApiError ? error.requestId : null;
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-10 text-center" role="alert">
      <p className="font-semibold">Something went wrong</p>
      <p className="text-sm text-muted-foreground">{errorMessage(error)}</p>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
      {requestId ? <p className="text-xs text-muted-foreground">Reference: {requestId}</p> : null}
    </div>
  );
}

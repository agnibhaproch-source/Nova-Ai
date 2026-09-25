/** ApiError + the single source of user-facing error copy (docs/32 §5). */

export type ErrorDetail = { field?: string; issue?: string; message?: string; [k: string]: unknown };

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public requestId: string | null = null,
    public retryable = false,
    public retryAfter: number | null = null,
    public details: ErrorDetail[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Envelope = {
  error?: {
    code?: string;
    message?: string;
    request_id?: string;
    retryable?: boolean;
    retry_after_seconds?: number;
    details?: ErrorDetail[];
  };
};

export async function toApiError(res: Response): Promise<ApiError> {
  let body: Envelope = {};
  try {
    body = (await res.json()) as Envelope;
  } catch {
    /* non-JSON body */
  }
  const e = body.error ?? {};
  const retryHeader = res.headers.get("retry-after");
  return new ApiError(
    res.status,
    e.code ?? "INTERNAL_ERROR",
    e.message ?? MESSAGES.INTERNAL_ERROR!,
    e.request_id ?? res.headers.get("x-request-id"),
    e.retryable ?? res.status >= 500,
    e.retry_after_seconds ?? (retryHeader ? Number(retryHeader) : null),
    e.details ?? [],
  );
}

const MESSAGES: Record<string, string> = {
  AUTH_REQUIRED: "Please log in to continue.",
  INVALID_CREDENTIALS: "Incorrect email or password.",
  ACCOUNT_LOCKED: "Too many attempts. Try again later.",
  ACCOUNT_SUSPENDED: "This account has been suspended. Contact support.",
  CSRF_FAILED: "Your session needs to be refreshed. Reload the page.",
  RATE_LIMITED: "You're doing that too often. Try again shortly.",
  PROVIDER_UNAVAILABLE: "Nova's AI provider is having trouble. Try again shortly.",
  PROVIDER_TIMEOUT: "The AI provider took too long to respond.",
  PROVIDER_RATE_LIMITED: "Your Groq API key has hit its rate limit. Try again in a moment.",
  MODEL_NOT_AVAILABLE: "This model isn't available. Choose another model.",
  CONTEXT_TOO_LARGE: "Your message is too long for this model. Shorten it.",
  GENERATION_IN_PROGRESS: "Wait for the current response to finish or stop it.",
  GENERATION_INTERRUPTED: "The response was interrupted. Retry to generate it again.",
  SERVICE_DEGRADED: "This feature is temporarily unavailable.",
  INTERNAL_ERROR: "Something went wrong. Please try again.",
};

/** Server messages are already user-safe; fall back to local copy by code. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message || MESSAGES[err.code] || MESSAGES.INTERNAL_ERROR!;
  return MESSAGES.INTERNAL_ERROR!;
}

/** Browser API client: same-origin /api/v1 via the BFF proxy, CSRF header on unsafe methods. */
import { ApiError, toApiError } from "./errors";

export function csrfToken(): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie.match(/(?:^|;\s*)nova_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]!) : "";
}

type Options = Omit<RequestInit, "body"> & { json?: unknown; retryCsrf?: boolean };

export async function api<T>(path: string, opts: Options = {}): Promise<T> {
  const { json, retryCsrf = true, ...init } = opts;
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (json !== undefined) headers.set("content-type", "application/json");
  if (!["GET", "HEAD"].includes(method)) headers.set("x-csrf-token", csrfToken());
  const res = await fetch(`/api/v1${path}`, {
    ...init,
    method,
    headers,
    body: json !== undefined ? JSON.stringify(json) : undefined,
    credentials: "same-origin",
  });
  if (!res.ok) {
    const err = await toApiError(res);
    // Stale CSRF cookie: refresh it via /auth/session once and retry (docs/32 §5).
    if (err.code === "CSRF_FAILED" && retryCsrf) {
      await fetch("/api/v1/auth/session", { credentials: "same-origin" });
      return api<T>(path, { ...opts, retryCsrf: false });
    }
    throw err;
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export type Envelope<T> = { data: T; meta?: Record<string, unknown> | null };
export type ListEnvelope<T> = {
  data: T[];
  page: { next_cursor: string | null; has_more: boolean };
  meta?: Record<string, unknown> | null;
};

export { ApiError };

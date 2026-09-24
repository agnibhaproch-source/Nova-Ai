import { api, type Envelope } from "@/lib/api/client";
import type { User } from "@/lib/types";

export const authApi = {
  login: (email: string, password: string) =>
    api<Envelope<User>>("/auth/login", { method: "POST", json: { email, password } }),
  signup: (body: { email: string; password: string; display_name: string; accept_terms: true }) =>
    api<Envelope<User>>("/auth/signup", { method: "POST", json: body }),
  logout: () => api<void>("/auth/logout", { method: "POST" }),
  forgot: (email: string) => api("/auth/password/forgot", { method: "POST", json: { email } }),
  reset: (token: string, new_password: string) =>
    api<void>("/auth/password/reset", { method: "POST", json: { token, new_password } }),
};

/** Only allow same-origin relative redirects after login. */
export function safeNext(next: string | null, fallback = "/chat"): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : fallback;
}

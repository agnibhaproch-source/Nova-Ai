import "server-only";

import { cookies, headers } from "next/headers";

import { serverEnv } from "@/lib/env";
import type { User } from "@/lib/types";

/** Server-side session check for layouts (docs/09 §13.3). FastAPI remains the authority. */
export async function getServerUser(): Promise<User | null> {
  const env = serverEnv();
  const jar = await cookies();
  const token = jar.get("nova_session");
  if (!token) return null;
  const h = await headers();
  try {
    const res = await fetch(`${env.API_INTERNAL_URL}/api/v1/auth/session`, {
      headers: {
        cookie: `nova_session=${token.value}`,
        "x-nova-proxy-secret": env.API_PROXY_SHARED_SECRET,
        "x-forwarded-for": h.get("x-forwarded-for") ?? "127.0.0.1",
      },
      cache: "no-store",
    });
    if (!res.ok) return null;
    const body = (await res.json()) as { data: { user: User } };
    return body.data.user;
  } catch {
    return null;
  }
}

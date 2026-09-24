/**
 * BFF proxy: forwards /api/v1/* to FastAPI with the proxy secret and streams bodies
 * (including SSE) without buffering. docs/05 §3, docs/13 §11.
 * The browser never talks to FastAPI or Groq directly.
 */
import type { NextRequest } from "next/server";

import { serverEnv } from "@/lib/env";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

const FORWARD_REQUEST = [
  "cookie",
  "authorization",
  "content-type",
  "accept",
  "idempotency-key",
  "last-event-id",
  "x-csrf-token",
  "origin",
  "referer",
  "user-agent",
  "x-request-id",
];
const FORWARD_RESPONSE = [
  "content-type",
  "cache-control",
  "retry-after",
  "ratelimit-limit",
  "ratelimit-remaining",
  "ratelimit-reset",
  "x-request-id",
  "location",
  "content-disposition",
  "x-accel-buffering",
];

function clientIp(req: NextRequest): string {
  const fwd = req.headers.get("x-forwarded-for");
  if (fwd) return fwd.split(",")[0]!.trim();
  return req.headers.get("x-real-ip") ?? "127.0.0.1";
}

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const env = serverEnv();
  const { path } = await ctx.params;
  const target = `${env.API_INTERNAL_URL}/api/v1/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;

  const headers = new Headers();
  for (const name of FORWARD_REQUEST) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }
  headers.set("x-nova-proxy-secret", env.API_PROXY_SHARED_SECRET);
  headers.set("x-forwarded-for", clientIp(req));
  headers.set("x-forwarded-proto", req.nextUrl.protocol.replace(":", ""));

  const hasBody = !["GET", "HEAD"].includes(req.method);
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: hasBody ? req.body : undefined,
      // Node fetch requires half-duplex for streamed request bodies.
      ...(hasBody ? ({ duplex: "half" } as Record<string, string>) : {}),
      redirect: "manual",
      signal: req.signal,
      cache: "no-store",
    });
  } catch {
    return Response.json(
      {
        error: {
          code: "SERVICE_DEGRADED",
          message: "Nova is temporarily unavailable. Please try again.",
          details: [],
          request_id: headers.get("x-request-id") ?? "-",
          retryable: true,
        },
      },
      { status: 503 },
    );
  }

  const out = new Headers();
  for (const name of FORWARD_RESPONSE) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }
  for (const cookie of upstream.headers.getSetCookie()) out.append("set-cookie", cookie);
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export { proxy as DELETE, proxy as GET, proxy as PATCH, proxy as POST, proxy as PUT };

/**
 * Next.js 16 proxy (formerly middleware): security headers + CSP nonce, and a fast UX
 * redirect for unauthenticated users. Real authorization is always enforced by FastAPI.
 * docs/33 §5, docs/09 §13.3
 */
import { NextResponse, type NextRequest } from "next/server";

const APP_PREFIXES = ["/chat", "/c/", "/settings", "/onboarding", "/admin", "/quick"];

function csp(nonce: string, dev: boolean): string {
  const s3 = process.env.S3_PUBLIC_ENDPOINT ? new URL(process.env.S3_PUBLIC_ENDPOINT).origin : "";
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""} https://checkout.razorpay.com`,
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' data: blob: ${s3}`.trim(),
    "media-src 'self' blob:",
    `connect-src 'self' ${s3} https://api.razorpay.com https://lumberjack.razorpay.com${dev ? " ws:" : ""}`.trim(),
    "frame-src https://api.razorpay.com https://checkout.razorpay.com",
    "font-src 'self' data:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const hasSession = request.cookies.has("nova_session");

  if (APP_PREFIXES.some((p) => pathname === p.replace(/\/$/, "") || pathname.startsWith(p)) && !hasSession) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(pathname + search)}`;
    return NextResponse.redirect(url);
  }

  // Already signed in and sent to /login?next=… (e.g. the desktop Quick Chat window): go there.
  if (hasSession && (pathname === "/login" || pathname === "/signup")) {
    const next = request.nextUrl.searchParams.get("next");
    if (next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\")) {
      return NextResponse.redirect(new URL(next, request.url));
    }
  }

  const nonce = btoa(crypto.randomUUID());
  const policy = csp(nonce, process.env.NODE_ENV !== "production");
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("content-security-policy", policy);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", policy);
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("Cross-Origin-Opener-Policy", "same-origin");
  response.headers.set(
    "Permissions-Policy",
    'camera=(), microphone=(self), geolocation=(), payment=(self "https://checkout.razorpay.com")',
  );
  if (process.env.NODE_ENV === "production") {
    response.headers.set("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload");
  }
  return response;
}

export const config = {
  matcher: [
    // Pages only: skip the API proxy, static assets and images.
    "/((?!api/|_next/static|_next/image|favicon.ico|logo.svg|robots.txt).*)",
  ],
};

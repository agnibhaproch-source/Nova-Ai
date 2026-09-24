import type { NextConfig } from "next";

// Env: Next loads apps/web/.env, which in development is a symlink to the repo-root .env
// (docs/44 §3). In deployed environments variables come from the platform.
const nextConfig: NextConfig = {
  output: "standalone",
  // E2E runs its own dev server beside the normal one; each needs its own build dir.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  poweredByHeader: false,
  // No Next.js dev-tools badge ("N") on the website or inside the desktop app.
  devIndicators: false,
  reactStrictMode: true,
  // The BFF proxy streams SSE; never compress text/event-stream (docs/13 §11).
  compress: false,
};

export default nextConfig;

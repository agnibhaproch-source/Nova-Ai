import { isPlatform, release } from "@/lib/desktop/release";

/** Stable download links: /download/mac, /download/windows, /download/linux. */
export async function GET(_request: Request, ctx: RouteContext<"/download/[platform]">) {
  const { platform } = await ctx.params;
  const rel = isPlatform(platform) ? release(platform) : null;
  // A path (or the configured external URL) as-is: behind the production proxy request.url is the
  // container's internal address, so an absolute URL built from it would point at 0.0.0.0:3000.
  return new Response(null, { status: 307, headers: { Location: rel ? rel.url : "/download", "Cache-Control": "no-store" } });
}

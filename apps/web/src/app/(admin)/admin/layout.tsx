import Link from "next/link";
import { notFound } from "next/navigation";

import { Logo } from "@/components/common/logo";
import { getServerUser } from "@/lib/auth/server-session";

const NAV = [
  ["/admin", "Dashboard"],
  ["/admin/users", "Users"],
  ["/admin/usage", "Usage"],
  ["/admin/analytics", "Analytics"],
  ["/admin/plans", "Plans"],
  ["/admin/models", "Models"],
  ["/admin/moderation", "Moderation"],
  ["/admin/errors", "Errors"],
  ["/admin/health", "Health"],
  ["/admin/audit-logs", "Audit logs"],
] as const;

// UI gate only — FastAPI enforces roles on every /admin request (docs/36 §1).
export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const user = await getServerUser();
  if (!user || user.role === "user") notFound();
  const env = process.env.APP_ENV ?? "development";
  return (
    <div className="flex min-h-dvh flex-col md:flex-row">
      <aside className="border-b border-border bg-surface p-3 md:w-[232px] md:border-b-0 md:border-r">
        <div className="mb-4 flex items-center justify-between px-2">
          <Link href="/chat"><Logo /></Link>
          <span className={env === "production" ? "rounded bg-destructive px-1.5 text-xs text-white" : "rounded bg-warning px-1.5 text-xs"}>{env.toUpperCase()}</span>
        </div>
        <nav className="flex gap-1 overflow-x-auto md:flex-col">
          {NAV.map(([href, label]) => (
            <Link key={href} href={href} className="whitespace-nowrap rounded-md px-3 py-2 text-sm hover:bg-accent">{label}</Link>
          ))}
        </nav>
      </aside>
      <main className="min-w-0 flex-1 p-4 md:p-6">{children}</main>
    </div>
  );
}

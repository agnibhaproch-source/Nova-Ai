import Link from "next/link";
import { redirect } from "next/navigation";

import { LogoMark } from "@/components/common/logo";
import { getServerUser } from "@/lib/auth/server-session";

export default async function AuthLayout({ children }: { children: React.ReactNode }) {
  if (await getServerUser()) redirect("/chat");
  return (
    <main className="flex min-h-dvh items-center justify-center bg-surface px-4 py-10">
      <div className="w-full max-w-[400px] space-y-6 rounded-xl border border-border bg-surface-raised p-8 shadow-sm">
        <Link href="/" className="mx-auto block w-fit" aria-label="NOVA AI home">
          <LogoMark className="size-9" />
        </Link>
        {children}
      </div>
    </main>
  );
}

import Link from "next/link";

import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-4 px-4 text-center">
      <h1 className="text-2xl font-semibold">This page doesn&apos;t exist</h1>
      <p className="text-muted-foreground">It may have been moved or deleted.</p>
      <Button asChild><Link href="/chat">Go to Nova</Link></Button>
    </main>
  );
}

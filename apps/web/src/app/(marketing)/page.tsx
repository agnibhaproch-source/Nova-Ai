import { BookOpen, Code2, Globe, Lock, Sparkles, Zap } from "lucide-react";
import Link from "next/link";

import { Logo } from "@/components/common/logo";
import { Button } from "@/components/ui/button";
import { getServerUser } from "@/lib/auth/server-session";

const FEATURES = [
  { icon: Zap, title: "Instant answers", body: "Responses stream in as they're written, powered by Groq's fast inference." },
  { icon: BookOpen, title: "Your documents", body: "Ask questions about PDFs, slides and spreadsheets with page-level citations." },
  { icon: Globe, title: "Live web search", body: "Get current information with sources you can check." },
  { icon: Code2, title: "Runs code safely", body: "Calculations and data work in an isolated sandbox." },
  { icon: Sparkles, title: "Remembers what matters", body: "Opt-in memory you can review, edit or delete anytime." },
  { icon: Lock, title: "Private by design", body: "Your conversations are never used for training or analytics." },
];

export default async function Landing() {
  const user = await getServerUser();
  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-10 border-b border-border/60 bg-background/80 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4">
          <Logo />
          <nav className="flex items-center gap-2">
            <Button asChild variant="ghost"><Link href="/download">Mac app</Link></Button>
            <Button asChild variant="ghost"><Link href="/pricing">Pricing</Link></Button>
            {user ? (
              <Button asChild><Link href="/chat">Open Nova</Link></Button>
            ) : (
              <>
                <Button asChild variant="ghost"><Link href="/login">Log in</Link></Button>
                <Button asChild><Link href="/signup">Get started</Link></Button>
              </>
            )}
          </nav>
        </div>
      </header>
      <main>
        <section className="mx-auto flex min-h-[70vh] max-w-3xl flex-col items-center justify-center gap-6 px-4 py-20 text-center">
          <h1 className="text-4xl font-bold tracking-tight lg:text-5xl">Think faster with Nova.</h1>
          <p className="max-w-xl text-lg text-muted-foreground">
            A fast, private AI assistant for writing, coding, research, and your documents.
          </p>
          <div className="flex flex-wrap justify-center gap-3">
            <Button asChild size="lg"><Link href={user ? "/chat" : "/signup"}>Get started — it&apos;s free</Link></Button>
          </div>
        </section>
        <section className="mx-auto grid max-w-6xl gap-4 px-4 pb-24 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.title} className="rounded-xl border border-border bg-surface-raised p-6">
              <f.icon className="mb-3 size-5 text-primary" />
              <h2 className="font-semibold">{f.title}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{f.body}</p>
            </div>
          ))}
        </section>
      </main>
      <footer className="border-t border-border py-8 text-center text-sm text-muted-foreground">© NOVA AI</footer>
    </div>
  );
}

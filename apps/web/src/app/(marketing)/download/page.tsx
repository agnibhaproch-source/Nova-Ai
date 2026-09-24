import { Apple, Camera, Keyboard, Layers, MessageSquare, Monitor, Move, Terminal } from "lucide-react";
import Link from "next/link";

import { Logo } from "@/components/common/logo";
import { Button } from "@/components/ui/button";
import { getServerUser } from "@/lib/auth/server-session";
import { release } from "@/lib/desktop/release";

export const metadata = { title: "Download Nova for Mac" };

const FEATURES = [
  { icon: Keyboard, title: "Option + / from anywhere", body: "A floating Nova chat opens over any app — no browser needed." },
  { icon: Camera, title: "Option + \\ for screenshots", body: "Captures your screen (never the Nova window) straight into the chat — even while it's hidden." },
  { icon: Move, title: "Floats where you put it", body: "Always on top, movable and resizable, with adjustable opacity." },
  { icon: MessageSquare, title: "Same Nova, same memory", body: "Your account, chats, memories and settings — exactly as on the website." },
];

export default async function Download() {
  const user = await getServerUser();
  const rel = release("mac");
  const win = release("windows");
  const linux = release("linux");
  return (
    <div className="min-h-dvh">
      <header className="border-b border-border/60">
        <div className="mx-auto flex h-16 max-w-5xl items-center justify-between px-4">
          <Link href="/"><Logo /></Link>
          <Button asChild variant="ghost">{user ? <Link href="/chat">Open Nova</Link> : <Link href="/login">Log in</Link>}</Button>
        </div>
      </header>
      <main className="mx-auto max-w-3xl space-y-10 px-4 py-16">
        <section className="space-y-4 text-center">
          <Layers className="mx-auto size-10 text-primary" aria-hidden />
          <h1 className="text-3xl font-bold tracking-tight">Nova for Mac</h1>
          <p className="text-muted-foreground">Quick Chat one shortcut away, in every app.</p>
          {rel ? (
            <div className="space-y-2">
              <Button asChild size="lg">
                <a href="/download/mac" download>
                  <Apple className="size-5" /> Download for Mac
                </a>
              </Button>
              <p className="text-xs text-muted-foreground">
                Apple Silicon and Intel · macOS 12 or later{rel.sizeMb ? ` · ${rel.sizeMb} MB` : ""}
              </p>
              {win || linux ? (
                <div className="flex flex-wrap justify-center gap-2 pt-2">
                  {win ? (
                    <Button asChild variant="outline" size="sm">
                      <a href="/download/windows" download><Monitor className="size-4" /> Windows{win.sizeMb ? ` · ${win.sizeMb} MB` : ""}</a>
                    </Button>
                  ) : null}
                  {linux ? (
                    <Button asChild variant="outline" size="sm">
                      <a href="/download/linux" download><Terminal className="size-4" /> Linux AppImage{linux.sizeMb ? ` · ${linux.sizeMb} MB` : ""}</a>
                    </Button>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : (
            <p className="rounded-lg border border-border px-4 py-3 text-sm text-muted-foreground">
              The Mac app hasn&apos;t been published on this server yet. (Admins: run <code>make desktop-release</code>.)
            </p>
          )}
        </section>

        <section className="grid gap-4 sm:grid-cols-2">
          {FEATURES.map((f) => (
            <div key={f.title} className="rounded-xl border border-border bg-surface-raised p-4">
              <f.icon className="mb-2 size-5 text-primary" aria-hidden />
              <p className="font-medium">{f.title}</p>
              <p className="text-sm text-muted-foreground">{f.body}</p>
            </div>
          ))}
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold">Install</h2>
          <ol className="list-decimal space-y-2 pl-5 text-sm">
            <li>Open <strong>Nova-mac.dmg</strong> and drag <strong>Nova</strong> into <strong>Applications</strong>.</li>
            <li>
              Open Nova from Applications. If macOS says it can&apos;t verify the developer, open
              <strong> System Settings → Privacy &amp; Security</strong> and click <strong>Open Anyway</strong>.
            </li>
            <li>Sign in inside the Nova window — the same account you use here.</li>
            <li>
              For screenshots, allow Nova in <strong>System Settings → Privacy &amp; Security → Screen Recording</strong>,
              then quit and reopen Nova.
            </li>
            <li>
              Nova lives in the menu bar and starts at login. Closing its window or pressing ⌘Q keeps it running in the
              background — press <kbd>Option</kbd> + <kbd>/</kbd> anytime. To really quit: <kbd>Option</kbd> + <kbd>Shift</kbd> + <kbd>Q</kbd>, or menu-bar icon → Quit Nova; then reopen it from Applications.
            </li>
            <li className="text-muted-foreground">
              Windows: run the installer (SmartScreen: More info → Run anyway), then Alt + / . Linux: make the AppImage
              executable and run it, then Alt + / .
            </li>
          </ol>
        </section>
      </main>
    </div>
  );
}

import { LogoMark } from "@/components/common/logo";

export function EmptyChat({ name, compact }: { name: string; compact?: boolean }) {
  if (compact)
    return (
      <div className="flex flex-col items-center gap-2 px-4 pt-10 text-center">
        <LogoMark className="size-8" />
        <p className="font-semibold">Ask anything, {name}</p>
        <p className="text-xs text-muted-foreground">Press / anytime to open Quick Chat · Esc to close</p>
      </div>
    );
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col items-center gap-6 px-4 pt-[18vh] text-center">
      <LogoMark className="size-10" />
      <h1 className="text-2xl font-semibold md:text-3xl">How can I help, {name}?</h1>
    </div>
  );
}

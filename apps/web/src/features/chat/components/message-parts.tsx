"use client";

import {
  Calculator,
  Check,
  ChevronRight,
  Code2,
  ExternalLink,
  FileText,
  Globe,
  Loader2,
  Search,
  TriangleAlert,
} from "lucide-react";
import { useState } from "react";

import { useImageUrl } from "@/features/files/api";
import { CodeBlock } from "@/features/markdown/code-block";
import { Markdown } from "@/features/markdown/markdown";
import type { Citation, MessagePart } from "@/lib/types";
import { cn } from "@/lib/utils";

const TOOL_ICON: Record<string, typeof Globe> = {
  web_search: Globe,
  file_search: Search,
  calculator: Calculator,
  code_execution: Code2,
};

type Rec = Record<string, unknown>;
const str = (v: unknown) => (typeof v === "string" ? v : v == null ? "" : String(v));

/** Renders an assistant message's ordered parts (docs/12 §9, docs/22 §9, docs/24 §7). */
export function MessageParts({ parts, streaming, citations }: { parts: MessagePart[]; streaming: boolean; citations: Citation[] }) {
  const results = new Map(parts.filter((p) => p.type === "tool_result" || p.type === "code").map((p) => [p.position - 1, p]));
  const lastText = [...parts].reverse().find((p) => p.type === "text");
  return (
    <div className="space-y-3">
      {parts.map((p) => {
        if (p.type === "text")
          return p.text ? (
            <div key={p.position} className={cn(streaming && p === lastText && "nova-cursor-host")}>
              <Markdown content={p.text} streaming={streaming && p === lastText} />
            </div>
          ) : null;
        if (p.type === "tool_call") {
          const result = results.get(p.position);
          return result?.type === "code" ? (
            <CodeRun key={p.position} part={result} running={p.status === "running"} />
          ) : (
            <ToolActivity key={p.position} call={p} result={result} />
          );
        }
        return null;
      })}
      {citations.length ? <Sources citations={citations} /> : null}
    </div>
  );
}

function ToolActivity({ call, result }: { call: MessagePart; result?: MessagePart }) {
  const [open, setOpen] = useState(false);
  const name = str(call.tool_name ?? result?.tool_name);
  const Icon = TOOL_ICON[name] ?? Search;
  const status = str(result?.status ?? call.status ?? "running");
  const running = status === "running" || status === "pending";
  const failed = !running && status !== "succeeded";
  const display = (result?.display ?? null) as Rec | null;
  return (
    <div className="rounded-lg border border-border text-sm">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        disabled={running}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-muted-foreground"
      >
        {running ? <Loader2 className="size-4 animate-spin" /> : failed ? <TriangleAlert className="size-4 text-warning" /> : <Icon className="size-4" />}
        <span className="min-w-0 flex-1 truncate">
          {running ? str(call.label) || "Working…" : str(result?.summary) || str(call.label)}
        </span>
        {!running ? <ChevronRight className={cn("size-4 transition-transform", open && "rotate-90")} /> : null}
      </button>
      {open && display ? (
        <div className="border-t border-border px-3 py-2">
          <ToolDisplay name={name} display={display} />
        </div>
      ) : null}
    </div>
  );
}

function ToolDisplay({ name, display }: { name: string; display: Rec }) {
  if (name === "calculator")
    return (
      <p className="font-mono text-sm">
        {str(display.expression)} = <strong>{str(display.result)}</strong>
      </p>
    );
  const results = (display.results as Rec[] | undefined) ?? [];
  if (!results.length) return <p className="text-muted-foreground">No results.</p>;
  return (
    <ol className="space-y-1">
      {results.map((r, i) => (
        <li key={i} className="flex items-baseline gap-2">
          <span className="text-xs text-muted-foreground">[{str(r.n)}]</span>
          {name === "web_search" ? (
            <a href={str(r.url)} target="_blank" rel="noreferrer noopener" className="truncate text-primary hover:underline">
              {str(r.title) || str(r.url)} <span className="text-muted-foreground">· {str(r.site)}</span>
            </a>
          ) : (
            <span className="truncate">
              {str(r.filename)}
              {r.page ? <span className="text-muted-foreground"> · p. {str(r.page)}</span> : null}
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}

function CodeRun({ part, running }: { part: MessagePart; running: boolean }) {
  const [open, setOpen] = useState(true);
  const exit = part.exit_code as number | null | undefined;
  const timedOut = Boolean(part.timed_out);
  const images = (part.images as string[] | undefined) ?? [];
  const ok = !timedOut && exit === 0;
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <div className="flex items-center gap-2 border-b border-border bg-surface px-3 py-1.5 text-xs text-muted-foreground">
        <Code2 className="size-3.5" />
        <span className="flex-1">Python</span>
        {running ? (
          <Loader2 className="size-3.5 animate-spin" />
        ) : (
          <span className={cn("rounded px-1.5", ok ? "bg-success/15 text-success" : "bg-destructive/15 text-destructive")}>
            {timedOut ? "Timed out" : ok ? <Check className="inline size-3" /> : `Exit ${exit ?? "?"}`}
          </span>
        )}
        {typeof part.duration_ms === "number" ? <span>{(part.duration_ms / 1000).toFixed(1)}s</span> : null}
        <button type="button" onClick={() => setOpen((o) => !o)} className="hover:text-foreground" aria-expanded={open}>
          {open ? "Hide" : "Show"}
        </button>
      </div>
      {open ? (
        <>
          <CodeBlock code={str(part.text ?? part.code)} lang="python" streaming={false} />
          {str(part.stdout) ? <Output label="Output" text={str(part.stdout)} /> : null}
          {str(part.stderr) ? <Output label="Errors" text={str(part.stderr)} danger /> : null}
          {images.length ? (
            <div className="flex flex-wrap gap-2 border-t border-border p-2">
              {images.map((id) => (
                <FileImage key={id} id={id} className="max-h-80 rounded" />
              ))}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function Output({ label, text, danger }: { label: string; text: string; danger?: boolean }) {
  return (
    <div className="border-t border-border">
      <p className="px-3 pt-2 text-xs text-muted-foreground">{label}</p>
      <pre className={cn("max-h-72 overflow-auto px-3 py-2 font-mono text-xs whitespace-pre-wrap", danger && "text-destructive")}>{text}</pre>
    </div>
  );
}

export function FileImage({ id, className, alt = "" }: { id: string; className?: string; alt?: string }) {
  const { data: url } = useImageUrl(id);
  if (!url) return <div className={cn("size-24 animate-pulse rounded bg-accent", className)} />;
  // eslint-disable-next-line @next/next/no-img-element -- short-lived presigned URL, not optimizable
  return <img src={url} alt={alt} className={className} />;
}

function Sources({ citations }: { citations: Citation[] }) {
  const sorted = [...citations].sort((a, b) => a.index - b.index);
  return (
    <div className="space-y-1.5 pt-1">
      <p className="text-xs font-medium text-muted-foreground">Sources</p>
      <div className="flex flex-wrap gap-2">
        {sorted.map((c) => {
          const label =
            c.source_type === "web"
              ? c.title || c.site_name || c.url || "Web page"
              : `${c.filename ?? "Document"}${c.page_number ? ` · p. ${c.page_number}` : c.sheet_name ? ` · ${c.sheet_name}` : ""}`;
          const body = (
            <>
              <span className="text-muted-foreground">[{c.index}]</span>
              {c.source_type === "web" ? <Globe className="size-3.5 shrink-0" /> : <FileText className="size-3.5 shrink-0" />}
              <span className="truncate">{label}</span>
              {c.source_type === "web" ? <ExternalLink className="size-3 shrink-0 text-muted-foreground" /> : null}
            </>
          );
          const cls = "flex max-w-full items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-xs sm:max-w-72";
          return c.source_type === "web" && c.url ? (
            <a key={c.index} href={c.url} target="_blank" rel="noreferrer noopener" title={c.snippet ?? undefined} className={cn(cls, "hover:bg-accent")}>
              {body}
            </a>
          ) : (
            <span key={c.index} title={c.snippet ?? undefined} className={cls}>
              {body}
            </span>
          );
        })}
      </div>
    </div>
  );
}

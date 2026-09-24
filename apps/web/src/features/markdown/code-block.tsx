"use client";

import { Check, Copy, WrapText } from "lucide-react";
import { memo, useEffect, useState } from "react";

import { cn } from "@/lib/utils";

type Token = { content: string; htmlStyle?: Record<string, string> };

// Lazily load shiki and highlight into tokens rendered as React spans — no raw HTML
// injection (docs/33 §5). Languages load on demand.
async function highlight(code: string, lang: string): Promise<Token[][] | null> {
  try {
    const { codeToTokens, bundledLanguages } = await import("shiki");
    const language = lang in bundledLanguages ? lang : "text";
    const res = await codeToTokens(code, {
      lang: language as "text",
      themes: { light: "github-light", dark: "github-dark-dimmed" },
    });
    return res.tokens as Token[][];
  } catch {
    return null;
  }
}

export const CodeBlock = memo(function CodeBlock({
  code,
  lang,
  streaming,
}: {
  code: string;
  lang: string;
  streaming: boolean;
}) {
  const [tokens, setTokens] = useState<Token[][] | null>(null);
  const [copied, setCopied] = useState(false);
  const [wrap, setWrap] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (streaming) return; // highlight once the fence closes (docs/27 §7)
    let alive = true;
    void highlight(code, lang).then((t) => alive && setTokens(t));
    return () => {
      alive = false;
    };
  }, [code, lang, streaming]);

  const long = code.split("\n").length > 30;
  return (
    <div className="not-prose my-3 overflow-hidden rounded-lg border border-border bg-code-bg">
      <div className="flex h-9 items-center justify-between border-b border-border px-3 text-xs text-muted-foreground">
        <span className="lowercase">{lang || "text"}</span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            className="flex items-center gap-1 rounded px-1.5 py-1 hover:bg-accent"
            onClick={() => setWrap((w) => !w)}
            aria-pressed={wrap}
            aria-label="Toggle line wrap"
          >
            <WrapText className="size-3.5" />
          </button>
          <button
            type="button"
            className="flex items-center gap-1 rounded px-1.5 py-1 hover:bg-accent"
            onClick={async () => {
              await navigator.clipboard.writeText(code);
              setCopied(true);
              setTimeout(() => setCopied(false), 2000);
            }}
          >
            {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </div>
      <pre
        className={cn(
          "shiki overflow-x-auto p-4 font-mono text-[14px] leading-[1.55]",
          wrap && "whitespace-pre-wrap break-words",
          long && !expanded && "max-h-[600px] overflow-y-hidden",
        )}
      >
        <code>
          {tokens
            ? tokens.map((line, i) => (
                <span key={i} className="block">
                  {line.map((t, j) => (
                    <span key={j} style={t.htmlStyle as React.CSSProperties}>
                      {t.content}
                    </span>
                  ))}
                  {line.length === 0 ? "\n" : null}
                </span>
              ))
            : code}
        </code>
      </pre>
      {long && !expanded ? (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="w-full border-t border-border py-1.5 text-xs text-muted-foreground hover:bg-accent"
        >
          Show more
        </button>
      ) : null}
    </div>
  );
});

"use client";

import { memo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { CodeBlock } from "./code-block";

const SAFE_PROTOCOL = /^(https?:|mailto:)/i;

/** Only http(s)/mailto links survive; raw HTML is never rendered (docs/33 §5). */
function urlTransform(url: string): string {
  return SAFE_PROTOCOL.test(url) ? url : "";
}

function components(streaming: boolean): Components {
  return {
    a: ({ href, children }) =>
      href ? (
        <a href={href} target="_blank" rel="noopener noreferrer nofollow">
          {children}
        </a>
      ) : (
        <span>{children}</span>
      ),
    // Markdown images are shown as links, never loaded (no tracking pixels).
    img: ({ src, alt }) =>
      typeof src === "string" && src ? (
        <a href={src} target="_blank" rel="noopener noreferrer nofollow">
          {alt || src}
        </a>
      ) : null,
    pre: ({ children }) => <>{children}</>,
    code: ({ className, children }) => {
      const match = /language-([\w+#-]+)/.exec(className ?? "");
      const text = String(children ?? "");
      if (!match && !text.includes("\n")) return <code>{children}</code>;
      return <CodeBlock code={text.replace(/\n$/, "")} lang={match?.[1] ?? "text"} streaming={streaming} />;
    },
    table: ({ children }) => (
      <div className="overflow-x-auto">
        <table>{children}</table>
      </div>
    ),
    input: ({ checked }) => <input type="checkbox" checked={!!checked} readOnly disabled />,
  };
}

const staticComponents = components(false);
const streamingComponents = components(true);

export const Markdown = memo(function Markdown({
  content,
  streaming = false,
}: {
  content: string;
  streaming?: boolean;
}) {
  return (
    <div className="prose-nova">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeKatex, { trust: false, strict: "ignore", maxExpand: 1000 }]]}
        urlTransform={urlTransform}
        components={streaming ? streamingComponents : staticComponents}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
});

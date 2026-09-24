/** Incremental SSE parser for fetch ReadableStreams (docs/29 §7). Handles arbitrary chunk
 * boundaries, CRLF, comments (keep-alives) and multi-line data. */

export type SSEEvent = { id: number | null; event: string; data: string };

export class SSEParser {
  private buffer = "";
  private dataLines: string[] = [];
  private eventName = "message";
  private id: number | null = null;

  push(chunk: string): SSEEvent[] {
    this.buffer += chunk;
    const out: SSEEvent[] = [];
    let idx: number;
    while ((idx = this.buffer.search(/\r\n|\n|\r/)) !== -1) {
      // A trailing "\r" may be the first half of a CRLF split across chunks: wait for more data.
      if (this.buffer[idx] === "\r" && idx === this.buffer.length - 1) break;
      const line = this.buffer.slice(0, idx);
      const sepLen = this.buffer.startsWith("\r\n", idx) ? 2 : 1;
      this.buffer = this.buffer.slice(idx + sepLen);
      const ev = this.line(line);
      if (ev) out.push(ev);
    }
    return out;
  }

  private line(line: string): SSEEvent | null {
    if (line === "") {
      if (this.dataLines.length === 0) {
        this.eventName = "message";
        return null;
      }
      const ev = { id: this.id, event: this.eventName, data: this.dataLines.join("\n") };
      this.dataLines = [];
      this.eventName = "message";
      this.id = null;
      return ev;
    }
    if (line.startsWith(":")) return null;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "data") this.dataLines.push(value);
    else if (field === "event") this.eventName = value;
    else if (field === "id") this.id = /^\d+$/.test(value) ? Number(value) : null;
    return null;
  }
}

export async function* readSSE(body: ReadableStream<Uint8Array>): AsyncGenerator<SSEEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = new SSEParser();
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      for (const ev of parser.push(decoder.decode(value, { stream: true }))) yield ev;
    }
    for (const ev of parser.push(decoder.decode() + "\n\n")) yield ev;
  } finally {
    reader.releaseLock();
  }
}

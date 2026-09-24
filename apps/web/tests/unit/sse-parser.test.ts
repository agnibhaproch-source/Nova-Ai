import { describe, expect, it } from "vitest";

import { groupConversations } from "@/features/conversations/group";
import { SSEParser } from "@/lib/sse/parser";

const STREAM =
  "retry: 2000\n\n: ping\n\nid: 1\nevent: message_start\ndata: {\"a\":1}\n\n" +
  "id: 2\r\nevent: content_delta\r\ndata: {\"delta\":\"héllo\"}\r\n\r\n" +
  "id: 3\nevent: message_complete\ndata: line1\ndata: line2\n\n";

describe("SSEParser", () => {
  it("parses events regardless of chunk boundaries", () => {
    for (let split = 0; split <= STREAM.length; split++) {
      const p = new SSEParser();
      const events = [...p.push(STREAM.slice(0, split)), ...p.push(STREAM.slice(split))];
      expect(events.map((e) => [e.id, e.event])).toEqual([
        [1, "message_start"],
        [2, "content_delta"],
        [3, "message_complete"],
      ]);
      expect(events[1]!.data).toBe('{"delta":"héllo"}');
      expect(events[2]!.data).toBe("line1\nline2");
    }
  });

  it("ignores comments and retry-only blocks", () => {
    expect(new SSEParser().push(": ping\n\nretry: 5\n\n")).toEqual([]);
  });
});

describe("groupConversations", () => {
  it("groups pinned first, then by recency", () => {
    const now = new Date("2026-09-24T12:00:00Z");
    const mk = (id: string, iso: string, pinned = false) =>
      ({ id, last_message_at: iso, pinned }) as Parameters<typeof groupConversations>[0][number];
    const groups = groupConversations(
      [
        mk("p", "2026-01-01T00:00:00Z", true),
        mk("t", "2026-09-24T10:00:00Z"),
        mk("y", "2026-09-23T10:00:00Z"),
      ],
      now,
    );
    expect(groups.map((g) => g.label)).toEqual(["Pinned", "Today", "Yesterday"]);
  });
});

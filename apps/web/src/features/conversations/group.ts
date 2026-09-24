import { differenceInCalendarDays, format } from "date-fns";

import type { Conversation } from "@/lib/types";

/** Sidebar grouping in the user's local timezone (docs/11 §10). */
export function groupConversations(items: Conversation[], now = new Date()) {
  const groups: { label: string; items: Conversation[] }[] = [];
  const push = (label: string, c: Conversation) => {
    const g = groups.find((x) => x.label === label);
    if (g) g.items.push(c);
    else groups.push({ label, items: [c] });
  };
  for (const c of items) {
    if (c.pinned) {
      push("Pinned", c);
      continue;
    }
    const d = new Date(c.last_message_at);
    const days = differenceInCalendarDays(now, d);
    push(
      days <= 0 ? "Today" : days === 1 ? "Yesterday" : days <= 7 ? "Previous 7 days" : days <= 30 ? "Previous 30 days" : format(d, "MMMM yyyy"),
      c,
    );
  }
  return groups;
}

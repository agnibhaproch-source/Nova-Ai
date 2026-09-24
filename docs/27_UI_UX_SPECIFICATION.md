# 27 — UI/UX Specification

Visual direction: **modern, minimal, premium, professional, clean, fast.** NOVA AI has its own identity; do not copy ChatGPT (or any product's) branding, logo, icons, illustrations, copy, or source code.

## 1. Design tokens

Defined as CSS variables in `apps/web/src/styles/globals.css` and mapped into Tailwind v4 `@theme`. Colors in OKLCH.

### 1.1 Color

| Token | Light | Dark | Use |
|---|---|---|---|
| `--background` | oklch(0.995 0 0) | oklch(0.16 0.005 270) | App background |
| `--surface` | oklch(0.98 0.002 270) | oklch(0.20 0.006 270) | Sidebar, cards |
| `--surface-raised` | oklch(1 0 0) | oklch(0.24 0.007 270) | Composer, popovers, dialogs |
| `--foreground` | oklch(0.21 0.01 270) | oklch(0.95 0.003 270) | Primary text |
| `--muted-foreground` | oklch(0.50 0.01 270) | oklch(0.70 0.01 270) | Secondary text |
| `--border` | oklch(0.92 0.004 270) | oklch(0.30 0.008 270) | Hairlines |
| `--primary` (Nova Indigo) | oklch(0.55 0.20 275) | oklch(0.68 0.17 275) | Primary actions, focus, links |
| `--primary-foreground` | oklch(0.99 0 0) | oklch(0.15 0.02 275) | Text on primary |
| `--accent` | oklch(0.96 0.02 275) | oklch(0.28 0.04 275) | Hover backgrounds, selected rows |
| `--user-bubble` | oklch(0.95 0.01 275) | oklch(0.27 0.02 275) | User message bubble |
| `--success` / `--warning` / `--destructive` | oklch(0.60 0.15 150) / oklch(0.75 0.15 75) / oklch(0.58 0.21 25) | oklch(0.70 0.14 150) / oklch(0.80 0.14 75) / oklch(0.68 0.19 25) | Status |
| `--ring` | = `--primary` | = `--primary` | Focus ring |
| `--code-bg` | oklch(0.97 0.003 270) | oklch(0.13 0.005 270) | Code blocks |

All text/background pairs must meet ACC-004; CI runs axe on both themes.

### 1.2 Typography
- UI/Body: **Inter** (variable, via `next/font/google`, `display: swap`), fallback `ui-sans-serif, system-ui`.
- Code: **JetBrains Mono** (variable), fallback `ui-monospace, SFMono-Regular, Menlo`.
- Scale (px / line-height): `xs 12/16`, `sm 14/20`, `base 16/26` (message body), `lg 18/28`, `xl 20/28`, `2xl 24/32`, `3xl 30/36`, `4xl 36/40`, `5xl 48/52` (landing hero only).
- Weights: 400 body, 500 UI labels/buttons, 600 headings, 700 hero only.
- Message prose: 16 px, line-height 1.65, paragraph spacing 12 px, headings h1 22 / h2 19 / h3 17 px, 600.
- Code in messages: 14 px / 1.55.

### 1.3 Spacing, radius, elevation
- 4 px base grid. Common: 4, 8, 12, 16, 20, 24, 32, 48, 64.
- Radius: `sm 6px` (chips, inputs small), `md 8px` (buttons, menu items), `lg 12px` (cards, code blocks), `xl 16px` (composer, dialogs), `full` (avatars, pills).
- Shadows: `shadow-composer: 0 1px 2px rgb(0 0 0 / 0.04), 0 4px 16px rgb(0 0 0 / 0.06)` (dark: border-only + `0 4px 24px rgb(0 0 0 / 0.35)`); popovers `0 8px 30px rgb(0 0 0 / 0.12)`.

### 1.4 Motion
- Durations: 120 ms (hover/press), 180 ms (popover, tooltip), 220 ms (sidebar, dialogs), 300 ms (page-level fades).
- Easing: `cubic-bezier(0.2, 0.8, 0.2, 1)` (enter), `cubic-bezier(0.4, 0, 1, 1)` (exit).
- Message entrance: opacity 0→1 + translateY 4→0 px, 180 ms, only for newly sent/arrived messages (not on history load).
- Streaming cursor: 2 px × 1 em bar in `--primary`, blink 1 s steps; removed on completion.
- `prefers-reduced-motion: reduce` → all transforms disabled; opacity fades ≤ 120 ms.

### 1.5 Iconography
Lucide icons, 16 px in dense UI, 18 px in toolbar/composer, stroke 1.75. Logo: original NOVA mark (four-point star/spark in `--primary` gradient to oklch(0.62 0.18 300)), SVG in `public/logo.svg`.

## 2. Global layout (app)

```
┌───────────────┬──────────────────────────────────────────────────────────┐
│ Sidebar 272px │ TopBar 56px: [≡ (collapsed only)] Title ▾ · Model ▾            [Files][⋯] │
│               ├──────────────────────────────────────────────────────────┤
│ [+ New chat]  │                                                          │
│ [🔍 Search ⌘K]│         Message column (max-w 768px, centered, px-4)     │
│               │                                                          │
│ Pinned        │                                                          │
│ Today         │                                                          │
│ Yesterday     │                                                          │
│ Previous 7 d  │                                                          │
│ …             │                                                          │
│               │  ┌──── Composer (max-w 768px, sticky bottom, pb-4) ───┐  │
│ ───────────── │  │ [📎][🌐][</>]  textarea…               [🎤][➤/■] │  │
│ [Avatar Name ▾]│  └────────────────────────────────────────────────────┘  │
│  Plan badge   │   small disclaimer: "Nova can make mistakes. Verify important info."│
└───────────────┴──────────────────────────────────────────────────────────┘
```

## 3. Landing page (`/`)

- Header (64 px, sticky, blurred background `backdrop-blur-md` with 80% `--background`): logo + "NOVA AI", nav links (Features, Pricing, Privacy), right: "Log in" (ghost), "Get started" (primary).
- Hero (min-h 80vh): headline 48/52 700 "Think faster with Nova." subhead 18/28 muted "A fast, private AI assistant for writing, coding, research, and your documents." CTAs: "Get started — it's free" (primary lg), "See pricing" (outline). Below: an animated product preview (static screenshot image of the NOVA UI + subtle floating gradient orb; reduced-motion: static).
- Feature grid (3×2 cards, 1 column on mobile): Instant answers (streaming), Your documents (RAG with citations), Live web search, Runs code safely, Remembers what matters (controllable memory), Private by design.
- "How your data is handled" section: 3 bullets.
- Pricing teaser (plan cards from `GET /api/v1/billing/plans`, SSR with 5 min revalidate).
- Footer: © NOVA AI, Terms, Privacy, Status link.
- If a session cookie exists, "Open Nova" replaces CTAs (client check via `/auth/session`).

## 4. Auth pages

Centered card (max-w 400px, p-8, `--surface-raised`, radius xl, border), logo on top, title 24 px 600.

- **Login:** Email, Password (show/hide toggle), "Forgot password?" link, primary "Log in" (full width), footer "New to Nova? Create an account". Errors: inline under field for validation; banner above form for `INVALID_CREDENTIALS` ("Incorrect email or password."), `ACCOUNT_LOCKED` ("Too many attempts. Try again in N minutes."), `ACCOUNT_SUSPENDED`.
- **Signup:** Display name, Email, Password with strength meter (4 segments; zxcvbn-lite heuristic client-side, server authoritative), terms checkbox with links, "Create account". `EMAIL_ALREADY_REGISTERED` → inline "An account with this email exists. Log in?".
- **Forgot password:** email field → success state "If an account exists, we've sent a reset link." (always).
- **Reset password:** new password + confirm → success → redirect to login with toast.
- Loading: button shows spinner and disabled state; form fields disabled during submit.
- Enter submits; first field autofocused.

## 5. Onboarding (`/onboarding`)

Two-step card (max-w 560px) with step dots; step 1 chip multi-select; step 2 custom instructions textarea (placeholder examples) + memory switch with explanation; buttons "Skip" (ghost) / "Continue" / "Start chatting". Framer Motion slide between steps (x ±16 px, 220 ms).

## 6. Main chat

### 6.1 Empty state (`/chat`)
- Vertically centered (40% from top): logo mark 40 px, greeting 30 px 600 "How can I help, {first name}?".
- Composer placed directly beneath greeting (not at bottom) on ≥ md; on mobile composer stays at bottom.
- No suggestion cards (removed by product decision): the empty state is just the logo and "How can I help, {name}?".

### 6.2 Sidebar
- Width 272 px, `--surface`, right border.
- Top: logo (links `/chat`), collapse button (`PanelLeftClose` icon, tooltip "Close sidebar ⌘⇧S").
- "New chat" button (full width, outline, `SquarePen` icon, shortcut hint `⌘⇧O`).
- "Search chats" button opens the command palette.
- Conversation list (virtualized, `@tanstack/react-virtual`): group headers 12 px 500 uppercase muted, items 36 px tall, radius md, title truncated with ellipsis, active item `--accent` background + 500 weight. Hover shows `⋯` button (menu: Rename, Pin/Unpin, Archive, Delete). Rename edits inline (Enter save, Esc cancel).
- Infinite scroll: fetch next page when within 400 px of the end; skeleton rows (6) while loading.
- Streaming indicator: small pulsing dot at the right of an item whose generation is active.
- Bottom: user menu (avatar 28 px, name, plan badge) → dropdown: Settings, Usage, Upgrade (if free), Admin (if role), Theme submenu, Help, Log out.
- Empty state: "No conversations yet" muted text.

### 6.3 Top bar
- Height 56 px, sticky, background with 85% opacity + blur, bottom border appears only after scroll > 0.
- Left: sidebar toggle (when collapsed), conversation title (click → inline rename), model selector dropdown (display name + chevron; menu lists models with description and capability icons; plan-locked items show lock + badge).
- Right: "Files" (paperclip badge with count) opens attached files popover; `⋯` menu: Rename, Pin, Archive, Delete.

### 6.4 Message list
- Column max-width 768 px (`max-w-3xl`), horizontal padding 16 px (24 px ≥ md). Vertical gap between turns 24 px.
- **User message:** right-aligned bubble, max-width 85% of column, `--user-bubble`, radius 20 px (bottom-right 6 px), padding 10×16, preserves whitespace (`whitespace-pre-wrap`), attachments rendered above bubble (file chips / image thumbnails). Hover (or long-press on touch) action bar below: Copy, Edit (pencil). Branch navigator `‹ 2/3 ›` if siblings.
- **Edit mode:** bubble becomes a textarea with same width, buttons "Cancel" / "Send" (primary). Esc cancels, Enter (per send preference) submits.
- **Assistant message:** no bubble; left aligned full column width; avatar mark 24 px at left on ≥ md (hidden on mobile); prose rendering (§9). Action bar (always visible on last message, hover on others): Copy, Regenerate (with model submenu), Read aloud, Thumbs up, Thumbs down, `⋯` (Report, "Used memory" info when applicable). Branch navigator for siblings. Metadata tooltip on hover of timestamp: model display name, tokens, duration.
- **Pending:** three-dot typing indicator (dots 6 px, staggered opacity animation).
- **Tool activity rows:** inside the assistant message before/among text; 32 px rows with tool icon, label ("Searching the web for 'python release'"), spinner → check / x; click expands panel (radius lg, border, `--surface`).
- **Stopped:** muted label "Stopped" after content.
- **Failed:** inline alert (destructive tint, radius lg): "Something went wrong generating this response." + error detail (user-safe message) + "Retry" button.
- **Length:** muted note + "Continue" button.
- "Jump to latest" floating round button (36 px, bottom center above composer) when scrolled up.

### 6.5 Composer
- Container: max-w 768 px, radius xl, `--surface-raised`, border, `shadow-composer`, padding 12 px; focus-within → border `--ring` at 40% + ring 2 px.
- Attachment tray (above textarea when attachments exist): chips 40 px tall: file icon by type, name (truncate 24 chars), size / status (progress ring during upload, spinner processing, red on failure with retry), remove ✕. Images show 40×40 thumbnail.
- Textarea: auto-grow from 1 line (24 px) to max 240 px (then scroll), placeholder "Message Nova…", 16 px (prevents iOS zoom).
- Bottom row: left: Attach (`Paperclip` → menu: Upload file, Add from library), Web search toggle (`Globe`, pressed state `--accent` + `--primary` icon), Code toggle (`Code2`) — toggles only shown if capability enabled; right: Mic (dictation), Send (`ArrowUp` in 32 px circle, primary; disabled when empty or uploads pending) — replaced by **Stop** (`Square` filled) while generating.
- Behaviors: Enter sends / Shift+Enter newline (inverted if `send_with_enter=false`; then Cmd/Ctrl+Enter sends). IME composition respected (`isComposing`). Drafts persisted per conversation in `composer-store` (+ `localStorage` best-effort). Paste of images creates attachments; paste of > 8,000 chars offers "Attach as file" chip suggestion. Drag-and-drop anywhere over chat shows a full overlay "Drop files to attach".
- Quota hint: when remaining messages today ≤ 5 → muted line under composer "5 messages left today on Free · Upgrade".
- Disclaimer line under composer: 12 px muted, centered.

### 6.6 Command palette (`Cmd/Ctrl+K`)
Radix Dialog + `cmdk`-style list (implemented with shadcn `Command`): input "Search chats…", sections: "Actions" (New chat, Settings, Toggle theme), "Recent" (5 recent conversations when empty query), "Results" (search API results with highlighted snippet). Arrow keys navigate, Enter opens, Esc closes.

## 7. Code blocks

- Container radius lg, border, `--code-bg`; header bar 36 px: language label (lowercase, muted 12 px) left; right: "Copy" (icon + text, switches to "Copied" with check for 2 s), "Wrap" toggle for long lines.
- Body: Shiki highlighting with themes `github-light` / `github-dark-dimmed` (switch by theme), horizontal scroll (no wrap by default), max-height 600 px with "Show more" expander for longer blocks.
- While streaming: render plain monospace text; highlight once the closing fence arrives (or on completion).
- Inline code: `--code-bg`, radius sm, px 1.5, 0.9em.

## 8. Citations

- Marker: superscript pill (min-w 18 px, h 18 px, 11 px 600, `--accent` bg, `--primary` text, radius full) showing number; hover/focus → popover (max-w 320 px): source icon (file type icon or globe), title/filename (600), page/site line (muted), snippet (3 lines clamp), "Open source" link. Click on mobile opens a bottom sheet.
- Sources footer under the message: "Sources" collapsed row listing cited sources as compact chips; clicking opens the **Source panel** (right drawer 420 px on desktop, full-screen sheet on mobile) with full chunk text, highlighted snippet, and actions.

## 9. Markdown rendering

`react-markdown` + `remark-gfm` + `remark-math` + `rehype-katex`; no raw HTML. Components mapped: headings, lists (spacing 4 px between items), blockquote (left border 3 px `--border`, muted text), tables (horizontal scroll container, header `--surface`, zebra rows, 14 px), links (primary color, underline on hover, external links open new tab with rel attrs), images in markdown are **not** rendered (shown as link) to avoid tracking pixels, horizontal rule, task lists (read-only checkboxes), KaTeX display math centered with overflow-x auto.

## 10. File attachments UI

- In user messages: chips (document icon, name, type·size) → click downloads (or opens Source panel for processed docs showing extracted preview first 2,000 chars).
- Images: grid thumbnails (max 2 cols, radius lg, 4 px gap), lightbox on click (Esc to close, arrow keys to navigate).
- Files dialog (sidebar → "Files" or composer "Add from library"): table/list with name, type, size, status, date, actions (attach, download, delete); search field; filter by type.

## 11. Settings

Route `/settings/*` rendered inside the app shell as a two-column layout (≥ md): left nav 220 px (General, Profile, Personalization, Data controls, Security, API keys, Billing, Usage), right content max-w 720 px. On mobile: nav list page → section pages with back button.

Sections are cards with title 16 px 600, description 14 px muted, rows separated by hairlines; each row label left, control right. Saves are immediate for toggles (optimistic with rollback + toast on error) and explicit "Save" for text fields (disabled until dirty).

- **Personalization:** custom instructions & about me textareas with character counters (1500), memory switch, "Manage memories" button → dialog list (search, each row: content, category badge, created date, edit/delete; "Delete all").
- **Data controls:** Export data (button + status of latest export + download link), Archived chats (dialog list with unarchive), Trash (dialog list with restore/delete permanently + purge date), Delete all chats (destructive), Analytics opt-out switch.
- **Security:** change password form, sessions table (device, IP, last active, "This device" badge, Revoke), "Sign out of all other devices", Delete account (destructive dialog requiring password + typing DELETE).
- **API keys:** table (name, prefix `nova_sk_ab12…`, scopes, created, last used, expires, Revoke); "Create key" dialog (name, scopes checkboxes, expiry select: never/30/90/365 days) → secret reveal dialog with copy and warning. Free plan: upsell empty state.
- **Profile:** avatar uploader (circle 80 px, click to change, remove), display name, email (read-only).
- **General:** theme segmented control (System/Light/Dark), language select, send-with-Enter switch, default model select, timezone select (searchable).

## 12. Usage page (`/settings/usage`)

- Quota meters (progress bars with labels): Messages today (x / limit, resets at 00:00 UTC shown in local time), Tokens this month, Web searches today, Code runs today, Storage used, Voice minutes today.
- Chart: daily messages and tokens for last 30 days (Recharts bar chart, `--primary` fill).
- Table: recent requests (date, conversation title link, model, tokens, latency, status).
- Near-limit (≥ 80%) meters turn `--warning`; at limit `--destructive` + upgrade CTA.

## 13. Subscription / billing (`/settings/billing`)

- Current plan card: name, price/month, renewal date or "Cancels on {date}", status badge (Active, Pending, Halted — "Payment failed, update payment in Razorpay email", Cancelled).
- Plan comparison cards (Free / Plus / Pro): price in ₹, key limits list, CTA ("Current plan", "Upgrade", "Downgrade at period end").
- Upgrade → server creates subscription → Razorpay Checkout modal (loaded lazily) → on success handler → verifying state ("Confirming payment…" spinner) → success confetti-free check animation and plan refresh; failure → inline error with retry.
- Cancel: dialog "Your plan stays active until {date}" → confirm.
- Payment history table: date, amount, status, method, invoice id.

## 14. Admin UI (`/admin`)

Separate `AdminShell`: left nav (Dashboard, Users, Usage, Conversations, Health, Errors, Subscriptions, Payments, Audit logs, Moderation, Models, Settings), top bar with environment badge (e.g., red "PRODUCTION"), dense data tables (row height 40 px, 14 px text), filters bar, pagination, CSV export for tables (server-generated). Full spec in `36_ADMIN_PANEL.md`.

## 15. States catalogue

| State | Pattern |
|---|---|
| Loading (page) | Skeletons matching layout (sidebar rows, 3 message skeleton blocks); never full-screen spinners except auth redirects |
| Loading (action) | Button spinner + disabled; optimistic UI where safe (rename, pin, archive, feedback, preferences) |
| Empty | `EmptyState` (icon 32 px muted, title 16 px 600, description 14 px, optional CTA) |
| Error (query) | `ErrorState` inline with "Try again" (refetch); includes request id in small muted text for support |
| Error (mutation) | Toast (sonner) with message from error code map; destructive style for failures |
| Offline | Top banner "You're offline. Messages will send when you're back." — sending disabled while offline |
| Rate limited | Inline alert near composer with countdown from `Retry-After` |
| Quota exceeded | Inline alert with Upgrade CTA |
| Provider down | Inline alert "Nova's AI provider is having trouble. Try again shortly." |
| Not found | `not-found.tsx`: "This page doesn't exist" / conversation: "Conversation not found" + New chat |

## 16. Interaction states

- Hover: background `--accent` for list items/ghost buttons; primary buttons darken 6% (`color-mix`).
- Active/pressed: scale 0.98 (buttons), 80 ms.
- Focus-visible: 2 px ring `--ring`, 2 px offset (never removed); focus via mouse doesn't show ring.
- Disabled: 50% opacity, `cursor-not-allowed`, no hover effect.
- Selected: `--accent` + 500 weight + `aria-current`.

## 17. Keyboard shortcuts

| Shortcut (Mac / Win-Linux) | Action |
|---|---|
| ⌘K / Ctrl+K | Command palette / search chats |
| ⌘⇧O / Ctrl+Shift+O | New chat |
| ⌘⇧S / Ctrl+Shift+S | Toggle sidebar |
| ⌘⇧; / Ctrl+Shift+; | Copy last assistant response |
| ⌘⇧C / Ctrl+Shift+C | Copy last code block |
| ⌘/ / Ctrl+/ | Show shortcuts dialog |
| / (when not typing, or in the empty main composer) | Toggle Quick Chat (§17a) |
| Esc | Stop generation (composer focused, generating) · close dialogs · cancel edit |
| ↑ (empty composer) | Edit last user message |
| Enter / Shift+Enter | Send / newline (configurable) |
| ⌘⇧Space / Ctrl+Shift+Space | Toggle dictation |

Shortcuts are registered in one place (`src/lib/shortcuts.ts`) and listed in the shortcuts dialog.

### 17a. Quick Chat

A small floating chat workspace available on every signed-in page (like a compact companion window).

- **Open/close:** `/` when focus isn't in a text field, or when the main composer is focused and empty (so `/` typed mid-message is never hijacked). The top bar also has a Quick Chat button with a `/` hint. `Esc` closes it (unless a reply is streaming, where `Esc` stops generation first).
- **Floating & movable:** a free-floating window (420 × up to 640 px; on phones it spans the width). Drag it by its title bar (grip icon) to any part of the page — mouse, pen or touch; it's always kept fully on screen and re-clamped when the viewport resizes. Arrow keys move it when the title bar is focused (Shift = bigger steps); double-click the title bar to snap back to the bottom-right default. The position is remembered per browser (localStorage). Header: grip, title, New quick chat, Open in full view (`/c/{id}`), Pop out, Close.
- **Behaviour:** its own conversation, created inside the popup without navigating the page underneath; persists across route changes and reopens where it left off. It uses the same composer (attachments, tools, dictation), streaming and BYOK key entry as the main chat, and its chats appear in the sidebar history.
- **Pop out:** opens `/quick?c={id}` as a separate small browser window (`window.open(..., "popup,width=440,height=680")`) containing only the chat.
- **Limits:** `/` is an in-app shortcut and the in-page window lives in the tab. For a window that outlives the tab, use the browser extension (§17b).
- The last Quick Chat conversation is remembered (localStorage) and shared by the in-page window, the pop-out and the extension window.
- Code: `apps/web/src/features/quick-chat/`; E2E: `apps/web/tests/e2e/quick-chat.spec.ts`.

### 17b. Quick Chat browser extension

`apps/extension` (Manifest V3, Chrome/Edge/Brave) opens `/quick` in its own **popup-type browser window** — no tabs or address bar — so it:

- **survives closing the Nova website** (it's an independent window, not part of the tab);
- can be **moved anywhere on screen** and resized by the OS; bounds are remembered (`chrome.storage.local`);
- toggles with **Ctrl+Shift+1 / ⌘⇧1** (a *global* command: works while the browser is in the background) or the toolbar icon; pressing it while focused minimizes the window, again restores it;
- uses the normal Nova session cookie (sign in once in the browser); stores no credentials; the Nova address is set on its options page (https required except localhost).

Limits: extensions can't bind a bare `/`, and browsers don't allow "always on top" windows. E2E: `apps/web/tests/e2e/extension.spec.ts` (loads the unpacked extension, closes the site tab, keeps chatting in the window).

### 17c. Nova desktop app (macOS · Windows · Linux)

`apps/desktop` (Electron) is the "anywhere" Quick Chat — it works with no browser open:

- Window chrome: no title bar and no Quick Chat header bar (website popup and desktop app). The controls (settings, new chat, full view, pop-out/close; on Windows/Linux desktop also minimize/close) float over the top edge and appear only on hover or keyboard focus; the strip also drags the window. On macOS the system close/minimize buttons appear only when hovering the top-left corner (`titleBarStyle: customButtonsOnHover`).
- Chat history in Quick Chat (website popup and desktop app): a History button lists every saved chat (same list as the sidebar, newest first, paginated); picking one continues it. Per-chat Groq keys last 30 days after last use (`GROQ_USER_KEY_TTL_HOURS=720`), so reopened chats keep working.
- Drag and drop: files can be dropped anywhere on a chat view (messages or composer) on the website, in Quick Chat and in the desktop app; a dashed "Drop files to attach" overlay shows while dragging. Images are accepted whenever vision is enabled, documents when uploads are enabled. The desktop window ignores files dropped outside the drop zone.
- Sending: a message may be only attachments (e.g. just a screenshot); Send enables once they're uploaded, and the model gets an instruction to analyse them in place of text.
- Passkey gate: every launch first shows an **Unlock Nova** window; nothing else starts until the right passkey. A wrong passkey closes Nova; after 3 wrong passkeys in a row it is locked on that device for good (apps/desktop/README.md → Passkey).
- Runs in the background like ChatGPT's desktop app: closing the window or pressing ⌘Q only hides it, so the shortcut always works; it quits only via the tray's **Quit Nova**, the **Option/Alt + Shift + Q** force-quit shortcut (exits the whole app at once from anywhere; reopen from Applications), or on OS shutdown/restart/logout. It reloads itself after a renderer crash or if the server was unreachable. Tray/menu-bar app, starts at login. **Option/Alt + /** shows/hides an always-on-top floating window (all Spaces, over full-screen apps); **Option/Alt + \** screenshots the display under the pointer into Quick Chat and brings the window up with it attached. On Windows the window is excluded from all captures with `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` (verified via `GetWindowDisplayAffinity`; older Windows: `WDA_MONITOR` plus hide-for-the-shot); on macOS with `NSWindow.sharingType = NSWindowSharingNone`, also read back. On macOS, Screen Recording is granted once (macOS requires it for any capture), and the stable signing identity keeps the grant across restarts and updates. Global keys use a modifier by product decision: bare `/` and `\` would stop those characters from being typed in every other app. Inside Nova, plain `/` and `\` still work.
- The window is excluded from all screenshots and screen shares via OS content protection (Linux: hidden for the capture instant).
- It runs `/quick` from the configured Nova server in a persistent session: same account, chats, memories and settings as the website. Window opacity (Quick Chat → ⚙, 0–100%) sets the native window opacity; below 20% it reveals to 20% while the pointer is over it.
- Security: context isolation, sandboxed renderer, origin-checked `window.novaDesktop` bridge (capture, opacity, screenshot events); off-origin navigation opens in the default browser.
- **Download:** `/download` on the website (linked from the landing page, the user menu and Quick Chat settings). `make desktop-release url=https://<domain>` builds a universal `Nova-mac.dmg` with that server baked in and publishes it to `apps/web/public/downloads/`; or set `DESKTOP_MAC_DOWNLOAD_URL` to a release/CDN URL. Unsigned builds need "Open Anyway" once; production releases should be signed with a Developer ID and notarized (`CSC_LINK`, `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID` for electron-builder).
- E2E: `apps/web/tests/e2e/desktop.spec.ts` (Playwright Electron: always-on-top, shortcuts registered, toggle, opacity, screenshot delivery).

### 17d. Screenshots in chat

Camera button in the composer and `\` (in-page, when not typing): Screen Capture API in browsers (the in-page Quick Chat is hidden for the grabbed frame), native capture in the desktop app. Screenshots queue into the Quick Chat composer even while it's closed; up to 3 images per message (Groq vision limit). Messages with images are routed to the vision model (`qwen/qwen3.8-27b`) for that turn, and the system prompt tells the model to read all visible text/code and answer with complete code in the requested language.

## 18. Copywriting

Sentence case, friendly, concise; no exclamation marks in errors; never blame the user; show next step. Error copy is mapped from error codes in `src/lib/api/errors.ts` (`32_ERROR_HANDLING.md` §4).

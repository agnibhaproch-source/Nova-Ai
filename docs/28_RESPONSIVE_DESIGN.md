# 28 — Responsive Design

## 1. Breakpoints (Tailwind defaults)

| Name | Range | Tailwind prefix | Device class |
|---|---|---|---|
| Mobile | 0–767 px (min supported 360 px) | base | Phones |
| Tablet | 768–1023 px | `md:` | Tablets, small windows |
| Laptop | 1024–1279 px | `lg:` | Laptops |
| Desktop | 1280–1535 px | `xl:` | Desktop monitors |
| Large desktop | ≥ 1536 px | `2xl:` | Large/ultrawide |

Mobile-first CSS. Layout decisions use CSS (not JS) wherever possible; JS breakpoint hook `useBreakpoint()` (matchMedia) only for behavior differences (e.g., sidebar mode).

## 2. Sidebar

| Breakpoint | Mode | Default | Behavior |
|---|---|---|---|
| Mobile | Off-canvas drawer (Radix Dialog as `Sheet` from left), width `min(85vw, 320px)` | Closed | Opened via ≡ in top bar or edge swipe (from left 20 px, threshold 60 px); overlay `bg-black/40`; closes on navigation, overlay tap, Esc, swipe left |
| Tablet | Overlay drawer 288 px | Closed | Same as mobile but without swipe; top bar shows ≡ |
| Laptop | Persistent, 260 px | Open | Collapsible to hidden (content expands); state persisted in `ui-store` + localStorage |
| Desktop | Persistent, 272 px | Open | Same |
| Large desktop | Persistent, 288 px | Open | Same |

Collapse animation: width/translate 220 ms; reduced motion → instant.

## 3. Top bar

- Mobile: 52 px; left ≡, center title (truncate, tap → rename sheet), right: new chat (`SquarePen`) + `⋯`. Model selector moves into the composer's `⋯`/model chip (below).
- Tablet+: 56 px layout per `27_UI_UX_SPECIFICATION.md` §6.3.
- Safe areas: `padding-top: env(safe-area-inset-top)` in standalone PWA mode.

## 4. Message column

| Breakpoint | Column max width | Horizontal padding | User bubble max width | Assistant avatar |
|---|---|---|---|---|
| Mobile | 100% | 12 px | 88% | hidden |
| Tablet | 720 px | 16 px | 85% | hidden |
| Laptop | 768 px | 24 px | 80% | shown (24 px) |
| Desktop | 768 px | 24 px | 80% | shown |
| Large desktop | 768 px (optional "Wide mode" setting → 896 px, stored client-side) | 24 px | 75% | shown |

Code blocks and tables scroll horizontally inside their containers; the page itself never scrolls horizontally (`overflow-x: hidden` on the column, `min-w-0` on flex children).

## 5. Composer

- Mobile: fixed to bottom (`position: sticky` in the scroll container with `padding-bottom: max(8px, env(safe-area-inset-bottom))`); full width minus 8 px margins; radius 20 px; toolbar collapses: Attach (+) opens a bottom sheet with Upload file / Photo / Library / Web search toggle / Code toggle / Model; mic and send remain visible. Textarea max height 160 px. Uses `visualViewport` resize listener to keep the composer above the on-screen keyboard (iOS) and scroll the list to bottom when the keyboard opens if the user was at bottom.
- Tablet+: full toolbar inline; max height 240 px.
- Empty state (`/chat`): mobile → suggestions as horizontal scroll row (snap) above composer; tablet+ → centered greeting with composer below and 2×2 suggestions.

## 6. Navigation

- Mobile: settings are a stack — `/settings` shows a list; each section is its own page with back arrow; admin shows a top `Select`-based section switcher instead of left nav.
- Tablet: settings use tabs (horizontal scrollable) at top.
- Laptop+: left nav columns.
- Command palette: full-screen sheet on mobile, centered dialog (max-w 640 px, top 20vh) on tablet+.

## 7. Dialogs and overlays

| Component | Mobile | Tablet+ |
|---|---|---|
| Dialog (confirm, forms) | Bottom sheet (Radix Dialog styled; drag handle; max-h 90vh; scroll inside) | Centered modal, max-w 480 px (forms 560 px) |
| Popover (citations, menus) | Bottom sheet for citations; dropdown menus remain dropdowns if fitting, else sheet | Popover |
| Source panel | Full-screen sheet | Right drawer 420 px (overlays content < xl; pushes content ≥ xl) |
| Tooltips | Not shown (touch); labels via `aria-label` | Shown on hover/focus after 400 ms |
| Lightbox | Full-screen with swipe between images, pinch zoom (native) | Centered, max 90vw/90vh |

## 8. Tables

- User-facing tables (sessions, API keys, payments, usage): on mobile, each row becomes a card (label/value pairs) via a `ResponsiveTable` component that renders `<table>` on ≥ md and a list of cards below.
- Admin tables: horizontal scroll with sticky first column on mobile/tablet; column visibility menu; dense mode default on ≥ lg.

## 9. Admin UI

- Mobile: supported for read and simple actions (suspend, resolve flag); left nav → top section switcher; KPI cards stack 1 column; charts full-width 220 px tall.
- Tablet: KPI 2 columns; nav collapsible.
- Laptop+: persistent 232 px nav; KPI 4 columns; charts in 2-column grid.

## 10. Touch and input

- Touch targets ≥ 44×44 px (ACC-008): message action buttons use 36 px icons within 44 px hit areas on touch (`@media (pointer: coarse)`).
- Hover-only affordances (message action bars, conversation `⋯`) are always visible on `pointer: coarse` for the last message and via long-press (500 ms) context menu for others.
- Inputs use 16 px font on mobile to prevent iOS zoom.
- `-webkit-tap-highlight-color: transparent`; active states provide feedback.

## 11. Typography scaling

Message body 16 px at all sizes; landing hero 36 px mobile → 48 px ≥ lg; page titles 22 px mobile → 24 px ≥ md.

## 12. Testing

Playwright projects: `mobile-chrome` (Pixel 7, 412×915), `mobile-safari` (iPhone 14, 390×844), `tablet` (iPad Mini 768×1024), `desktop-chrome` (1440×900), `large` (1920×1080). Visual regression snapshots for chat, empty state, settings, admin dashboard per project (threshold 0.2%). A smoke assertion checks `document.documentElement.scrollWidth <= innerWidth` on every page (no horizontal overflow).

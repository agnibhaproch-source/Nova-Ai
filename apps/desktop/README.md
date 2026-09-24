# Nova desktop (Quick Chat anywhere)

A small tray app that keeps a floating Nova chat one shortcut away — in any app, with no browser
open — like ChatGPT's desktop companion window.

| Shortcut | macOS | Windows / Linux |
|---|---|---|
| Show / hide Quick Chat | **Option + /** | **Alt + /** |
| Screenshot into Quick Chat | **Option + \\** | **Alt + \\** |

- The window floats above other apps, can be dragged anywhere and resized, and remembers where you put it.
  Closing the window or pressing ⌘Q only hides it — Nova keeps running in the menu bar/tray (and
  starts at login), so the shortcut always works. To really quit: **Option/Alt + Shift + Q** from anywhere (kills the whole app at once), or menu-bar icon → **Quit Nova**; reopen it from Applications.
- **Screenshots** capture the display under your pointer at full resolution. The Nova window is
  excluded by the OS (content protection), so it never appears in the shot — even when open.
  The screenshot lands in the Quick Chat message box without opening the window; take several
  (up to 3 per message), then open Nova and ask about them. They're read by the vision model.
- **Same account and memory as the website:** the window runs Nova itself; sign in once and your
  chats, memories and settings are the same everywhere. All website settings, plus window opacity
  (100% → 0%), are in Quick Chat → ⚙.
- Inside the Nova window, plain `/` and `\` also work.

## Run / build
```bash
cd apps/desktop
pnpm install && node node_modules/electron/install.js   # once
pnpm start                       # NOVA_URL=https://nova.example.com pnpm start for another server
pnpm dist                        # .dmg (macOS) / .exe installer (Windows) / AppImage (Linux) in dist/
```
If you launch from a VS Code terminal, run `unset ELECTRON_RUN_AS_NODE` first.

## Passkey
Every launch starts with an **Unlock Nova** window; nothing else (popup, tray, shortcuts) starts
until the right passkey is entered. Wrong passkey → Nova closes; closing the window → Nova stays
closed (doesn't use a try). After **3 wrong passkeys in a row** (counted across launches, reset by a
correct one) Nova is locked on that device for good and only shows "Nova is locked on this device".
`src/passkey.js` ships only a salted scrypt hash of the passkey. The failure count is stored in two
places (`<userData>/.guard` and a hidden `.ai.nova.quickchat` file in Application Support /
%LOCALAPPDATA% / ~/.local/state), each with an HMAC; an edited record counts as locked. This is a
local gate: an admin of the machine can still delete those files, and a 5-digit passkey can be
brute-forced offline from the hash. To set your own passkey: `node scripts/set-passkey.js <passkey>`, then rebuild.
Development/test runs keep the guard inside their own data folder, and installed builds ignore
`NOVA_USER_DATA`, so tests can't lock (or unlock) a real install.

## Permissions
- **macOS:** Screen Recording must be allowed once: macOS asks on the first screenshot (System
  Settings → Privacy & Security → **Screen Recording** → Nova), then reopen Nova. No app can skip
  this; macOS requires it for any screen capture. macOS remembers the grant per signing identity, so
  builds are signed with a stable identity: run `scripts/signing-identity.sh` once per build machine
  (it stays in the gitignored `.signing/`), and `make desktop-release` signs with it. Ad-hoc builds
  would get a new identity every build and be asked again. Public releases should use an Apple
  Developer ID (`CSC_LINK`/`CSC_NAME`) plus notarization; until then users right-click → Open the
  first time. Recent macOS may also re-confirm screen access about once a month (an OS policy).
- **Windows 10 2004+ / 11:** nothing to grant. `src/display-affinity.js` calls
  `user32!SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)` through Koffi and checks it with
  `GetWindowDisplayAffinity`, so the window is left out of screenshots, recordings and screen
  shares. Older Windows falls back to `WDA_MONITOR` (black in captures), and Nova then hides the
  window for the instant of its own screenshot.
- **macOS capture exclusion:** the same module sets `NSWindow.sharingType = NSWindowSharingNone`
  through the Objective-C runtime (`-[NSWindow setSharingType:]`) and reads it back, so screenshots,
  recordings and screen shares by other apps leave Nova out. Koffi ships in the Windows and macOS
  builds (only that platform's binaries); Linux hides the window for the shot instead.
- **Linux:** the window is hidden for the instant of the capture instead.

## Security
Context isolation + sandboxed renderer; the page gets a tiny origin-checked bridge
(`window.novaDesktop`: capture, opacity, screenshot events). Navigation outside the Nova origin
opens in your browser. No Groq keys or secrets are stored by the app.

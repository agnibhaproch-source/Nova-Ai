# Nova Quick Chat (browser extension)

A floating Nova chat window you can open from anywhere with a keyboard shortcut — like a desktop
companion window. It's a separate browser window, so it **stays open when you close the Nova
tab**, and you can **drag it to any part of the screen** (it remembers where you put it and its size).

## Install (Chrome / Edge / Brave, developer mode)
1. Open `chrome://extensions`, turn on **Developer mode**.
2. **Load unpacked** → choose this folder (`apps/extension`).
3. The settings page opens: set the Nova address (default `http://localhost:3000`) and save.
4. Sign in to Nova in the same browser.

## Use
- **Ctrl+Shift+1** (Mac: **⌘⇧1**) or the toolbar icon: open / hide Quick Chat. The shortcut is
  global, so it works even when the browser isn't the active app (while the browser is running).
- Change the shortcut at `chrome://extensions/shortcuts`.
- The window resumes your last Quick Chat. Your Groq key is asked for once per chat, as in the main app.

## Notes
- Browser extensions can't bind a bare `/` key; inside the Nova website, `/` still opens the
  in-page Quick Chat.
- The window uses your normal Nova session cookies; no credentials are stored by the extension.
- Browsers don't allow extension windows to be pinned "always on top".

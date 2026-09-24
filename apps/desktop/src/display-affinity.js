// Keep the Nova window out of screenshots, screen recordings and screen shares, using each OS's
// own API directly (docs/27 §17c). Electron's setContentProtection does the same underneath; these
// explicit calls also read the setting back, so main.js knows whether it really applied.
//
// Windows: user32!SetWindowDisplayAffinity
// - WDA_EXCLUDEFROMCAPTURE (Windows 10 2004+): the window is left out of captures entirely.
// - WDA_MONITOR (older Windows): the window shows up black in captures instead.
// macOS: -[NSWindow setSharingType:NSWindowSharingNone] via the Objective-C runtime; the window's
//   contents aren't available to other processes' screenshots, recordings or screen shares.
// Linux has no equivalent; main.js hides the window for the instant of its own screenshot.
const WDA_NONE = 0x00;
const WDA_MONITOR = 0x01;
const WDA_EXCLUDEFROMCAPTURE = 0x11;
const NSWindowSharingNone = 0;
const NSWindowSharingReadOnly = 1;

let native; // undefined = not loaded yet, null = unavailable

function load() {
  if (native !== undefined) return native;
  native = null;
  try {
    if (process.platform === "win32") {
      const koffi = require("koffi");
      const user32 = koffi.load("user32.dll");
      native = {
        set: user32.func("bool __stdcall SetWindowDisplayAffinity(intptr_t hWnd, uint32_t dwAffinity)"),
        get: user32.func("bool __stdcall GetWindowDisplayAffinity(intptr_t hWnd, _Out_ uint32_t *pdwAffinity)"),
      };
    } else if (process.platform === "darwin") {
      const koffi = require("koffi");
      const objc = koffi.load("/usr/lib/libobjc.A.dylib");
      const sel = objc.func("intptr_t sel_registerName(const char *name)");
      // objc_msgSend must be called through a prototype matching each method (arm64 ABI).
      const sendId = objc.func("objc_msgSend", "intptr_t", ["intptr_t", "intptr_t"]);
      const sendUInt = objc.func("objc_msgSend", "uint64_t", ["intptr_t", "intptr_t"]);
      const sendSetUInt = objc.func("objc_msgSend", "void", ["intptr_t", "intptr_t", "uint64_t"]);
      const S = { window: sel("window"), sharingType: sel("sharingType"), setSharingType: sel("setSharingType:") };
      native = {
        // Electron hands over the window's content NSView; its -window is the NSWindow.
        nsWindow: (view) => sendId(view, S.window),
        set: (w, type) => sendSetUInt(w, S.setSharingType, type),
        get: (w) => Number(sendUInt(w, S.sharingType)),
      };
    }
  } catch (err) {
    console.warn("capture exclusion API unavailable:", err?.message ?? err);
    native = null;
  }
  return native;
}

/** The native handle (HWND on Windows, NSView* on macOS) as an integer. */
function handleOf(win) {
  const buf = win.getNativeWindowHandle();
  return buf.length >= 8 ? buf.readBigInt64LE(0) : buf.readInt32LE(0);
}

function getAffinity(win) {
  const api = load();
  if (!api || !win || win.isDestroyed()) return null;
  if (process.platform === "darwin") {
    const w = api.nsWindow(handleOf(win));
    return w ? api.get(w) : null;
  }
  const out = [0];
  return api.get(handleOf(win), out) ? out[0] : null;
}

/**
 * Excludes `win` from screen capture. Returns what the OS actually applied:
 * "exclude" (left out of captures), "monitor" (Windows before 2004: black in captures),
 * or "unavailable".
 */
function excludeFromCapture(win) {
  const api = load();
  if (!api || !win || win.isDestroyed()) return "unavailable";
  if (process.platform === "darwin") {
    const w = api.nsWindow(handleOf(win));
    if (!w) return "unavailable";
    api.set(w, NSWindowSharingNone);
    return api.get(w) === NSWindowSharingNone ? "exclude" : "unavailable";
  }
  const hwnd = handleOf(win);
  if (api.set(hwnd, WDA_EXCLUDEFROMCAPTURE) && getAffinity(win) === WDA_EXCLUDEFROMCAPTURE) return "exclude";
  if (api.set(hwnd, WDA_MONITOR) && getAffinity(win) === WDA_MONITOR) return "monitor";
  return "unavailable";
}

/** Makes `win` capturable again. */
function allowCapture(win) {
  const api = load();
  if (!api || !win || win.isDestroyed()) return false;
  if (process.platform === "darwin") {
    const w = api.nsWindow(handleOf(win));
    if (!w) return false;
    api.set(w, NSWindowSharingReadOnly);
    return api.get(w) === NSWindowSharingReadOnly;
  }
  return api.set(handleOf(win), WDA_NONE);
}

module.exports = {
  excludeFromCapture, allowCapture, getAffinity,
  WDA_NONE, WDA_MONITOR, WDA_EXCLUDEFROMCAPTURE, NSWindowSharingNone, NSWindowSharingReadOnly,
};

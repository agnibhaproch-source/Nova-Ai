// Nova desktop: a floating Quick Chat window on global shortcuts (docs/27 §17c).
// - Alt+/ (Option+/ on macOS) shows/hides the window from any app; the app lives in the tray.
// - Alt+Shift+Q force-quits the whole app (otherwise it keeps running in the background).
// - Alt+\ screenshots the screen (the Nova window is excluded from captures by the OS) and
//   drops the image into Quick Chat, then shows it ready for your question.
// - The window runs the Nova web app (/quick) with a persistent session: same account, chats
//   and memory as the website. No Groq calls or secrets live here.
const {
  app, BrowserWindow, Menu, Notification, Tray, desktopCapturer, dialog, globalShortcut, ipcMain,
  nativeImage, powerMonitor, screen, shell, systemPreferences,
} = require("electron");
const fs = require("node:fs");
const path = require("node:path");

const displayAffinity = require("./display-affinity");
const passkey = require("./passkey");

const SHORTCUTS = { toggle: "Alt+/", screenshot: "Alt+\\", kill: "Alt+Shift+Q" };
// Release builds bake in the website they're downloaded from (package.json "novaUrl", set by
// `make desktop-release`); NOVA_URL overrides for development.
const DEFAULT_URL = process.env.NOVA_URL || require("../package.json").novaUrl || "http://localhost:3000";
const cfgPath = () => path.join(app.getPath("userData"), "config.json");

function loadConfig() {
  try {
    return { baseUrl: DEFAULT_URL, bounds: null, opacity: 1, ...JSON.parse(fs.readFileSync(cfgPath(), "utf8")) };
  } catch {
    return { baseUrl: DEFAULT_URL, bounds: null, opacity: 1 };
  }
}
let config;
const saveConfig = () => fs.writeFileSync(cfgPath(), JSON.stringify(config, null, 2));

let win = null;
let tray = null;
// Nova keeps running in the background like ChatGPT's desktop app: closing the window or ⌘Q only
// hides it, so Option+/ always works. It really quits only from the tray's "Quit Nova" or when the
// OS shuts down / restarts / logs out.
let quitting = false;
let loadFailed = false;
// Set once the passkey was accepted this launch; nothing opens before that.
let unlocked = false;

function quitForReal() {
  quitting = true;
  app.quit();
}

// Option/Alt+Shift+Q: kill the whole app at once (window, tray, background process, shortcuts).
// No quit handlers or prompts run; reopen Nova from Applications / the Start menu.
function forceKill() {
  quitting = true;
  globalShortcut.unregisterAll();
  app.exit(0);
}
let peekTimer = null;
// What the OS confirmed for capture exclusion ("exclude" | "monitor" | "unavailable").
let captureAffinity = null;

const origin = () => new URL(config.baseUrl).origin;

function createWindow({ show }) {
  const b = config.bounds;
  win = new BrowserWindow({
    width: b?.width ?? 440,
    height: b?.height ?? 680,
    ...(b ? { x: b.x, y: b.y } : {}),
    minWidth: 340,
    minHeight: 420,
    show: false,
    title: "Nova",
    // No title bar: on macOS the close/minimize buttons appear only while hovering the top-left
    // corner; on Windows/Linux the page shows its own on hover (window.novaDesktop.minimize/hide).
    frame: false,
    ...(process.platform === "darwin" ? { titleBarStyle: "customButtonsOnHover" } : {}),
    alwaysOnTop: true,
    fullscreenable: false,
    skipTaskbar: process.platform !== "darwin",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      partition: "persist:nova", // keeps you signed in across restarts
    },
  });
  win.setAlwaysOnTop(true, "floating");
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.setContentProtection(true); // never appears in screenshots or screen shares
  if (process.platform === "win32" || process.platform === "darwin") {
    // Explicit SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE) on Windows and
    // NSWindow.sharingType = NSWindowSharingNone on macOS, read back to confirm; re-applied on show.
    captureAffinity = displayAffinity.excludeFromCapture(win);
    win.on("show", () => { captureAffinity = displayAffinity.excludeFromCapture(win); });
  }
  win.setOpacity(clampOpacity(config.opacity));
  win.loadURL(`${config.baseUrl}/quick`);

  // Stay inside Nova; open everything else in the default browser.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (e, url) => {
    // A file dropped outside the chat's drop zone: ignore it (the page attaches drops itself).
    if (url.startsWith("file:")) return e.preventDefault();
    if (new URL(url).origin !== origin()) {
      e.preventDefault();
      shell.openExternal(url);
    }
  });

  const remember = () => {
    if (!win || win.isMinimized()) return;
    config.bounds = win.getBounds();
    saveConfig();
  };
  win.on("moved", remember);
  win.on("resized", remember);
  // Closing hides it: the app keeps running in the tray so the shortcut always works.
  win.on("close", (e) => {
    if (!quitting) {
      e.preventDefault();
      win.hide();
    }
  });
  win.once("ready-to-show", () => show && showWindow());

  // Keep the popup usable: recover from renderer crashes and from the server being unreachable.
  win.webContents.on("render-process-gone", () => setTimeout(() => win?.reload(), 500));
  win.webContents.on("did-fail-load", (_e, code, _desc, _url, isMainFrame) => {
    if (isMainFrame && code !== -3) loadFailed = true; // -3 = aborted by a navigation
  });
  win.webContents.on("did-finish-load", () => { loadFailed = false; });
}

function clampOpacity(v) {
  return Math.max(0, Math.min(1, Number.isFinite(v) ? v : 1));
}

function showWindow() {
  if (!config || quitting || !unlocked) return; // not started/unlocked yet, or relaunching
  if (!win || win.isDestroyed()) createWindow({ show: false });
  if (loadFailed) win.loadURL(`${config.baseUrl}/quick`); // server was down earlier: try again
  win.show();
  win.focus();
}

function toggle() {
  if (win && win.isVisible() && win.isFocused()) win.hide();
  else showWindow();
}

// Nearly transparent windows reveal at 20% while the pointer is over them (so they can be found).
function updatePeek() {
  clearInterval(peekTimer);
  if (config.opacity >= 0.2) return;
  peekTimer = setInterval(() => {
    if (!win || !win.isVisible()) return;
    const p = screen.getCursorScreenPoint();
    const b = win.getBounds();
    const inside = p.x >= b.x && p.x <= b.x + b.width && p.y >= b.y && p.y <= b.y + b.height;
    win.setOpacity(inside ? 0.2 : config.opacity);
  }, 150);
}

function setOpacity(v) {
  config.opacity = clampOpacity(v);
  saveConfig();
  win?.setOpacity(config.opacity);
  updatePeek();
}

// macOS asks once per app identity (builds are signed with a stable identity, so this sticks).
// Not asked yet: trigger the system prompt by attempting a capture. Denied: guide the user once.
let permissionHelpShown = false;
async function ensureScreenPermission() {
  if (process.platform !== "darwin") return true;
  const status = systemPreferences.getMediaAccessStatus("screen");
  if (status === "granted") return true;
  if (status === "not-determined") {
    await desktopCapturer.getSources({ types: ["screen"], thumbnailSize: { width: 1, height: 1 } }).catch(() => {});
    return systemPreferences.getMediaAccessStatus("screen") === "granted";
  }
  if (permissionHelpShown) return false;
  permissionHelpShown = true;
  const { response } = await dialog.showMessageBox({
    type: "info",
    message: "Allow Nova to take screenshots",
    detail: "Turn on Nova in System Settings → Privacy & Security → Screen Recording, then reopen Nova. You only need to do this once.",
    buttons: ["Open Settings", "Reopen Nova", "Later"],
    defaultId: 0,
    cancelId: 2,
  });
  if (response === 0) shell.openExternal("x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture");
  if (response === 1) {
    app.relaunch();
    quitForReal();
  }
  return false;
}

/** Full-resolution PNG of the display under the pointer, without the Nova window. */
async function captureScreen() {
  const display = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
  const size = { width: Math.round(display.size.width * display.scaleFactor), height: Math.round(display.size.height * display.scaleFactor) };
  // Where the OS confirmed the exclusion the window is already left out; otherwise (Linux, older
  // Windows where it would show up black) hide it for the instant of the shot.
  const excluded = captureAffinity === "exclude";
  const hideForShot = !excluded && win?.isVisible();
  if (hideForShot) {
    win.hide();
    await new Promise((r) => setTimeout(r, 200));
  }
  try {
    const sources = await desktopCapturer.getSources({ types: ["screen"], thumbnailSize: size });
    const src = sources.find((s) => s.display_id === String(display.id)) ?? sources[0];
    if (!src || src.thumbnail.isEmpty()) throw new Error("Couldn't capture the screen.");
    return src.thumbnail.toDataURL();
  } finally {
    if (hideForShot) win.showInactive();
  }
}

async function screenshotToChat() {
  if (!(await ensureScreenPermission())) return;
  try {
    const dataUrl = await captureScreen();
    if (!win || win.isDestroyed()) createWindow({ show: false });
    const deliver = () => win.webContents.send("nova:screenshot", dataUrl);
    if (win.webContents.isLoading()) win.webContents.once("did-finish-load", () => setTimeout(deliver, 500));
    else deliver();
    showWindow(); // straight into Quick Chat with the screenshot attached, ready to ask
  } catch (err) {
    dialog.showErrorBox("Screenshot failed", String(err?.message ?? err));
  }
}

const label = (acc) => (process.platform === "darwin" ? acc.replace("Alt", "Option") : acc);

function registerShortcuts() {
  const failed = [];
  if (!globalShortcut.register(SHORTCUTS.toggle, toggle)) failed.push(label(SHORTCUTS.toggle));
  if (!globalShortcut.register(SHORTCUTS.screenshot, () => void screenshotToChat())) failed.push(label(SHORTCUTS.screenshot));
  if (!globalShortcut.register(SHORTCUTS.kill, forceKill)) failed.push(label(SHORTCUTS.kill));
  // A notification, not a modal: a blocking dialog would freeze Nova (and its other shortcuts).
  if (failed.length) {
    const body = `Another app is using ${failed.join(" and ")}. Close it and restart Nova to use ${failed.length > 1 ? "them" : "it"}.`;
    if (Notification.isSupported()) new Notification({ title: "Shortcut unavailable", body }).show();
    else console.warn(`Shortcut unavailable: ${body}`);
  }
}

function openSettings() {
  const s = new BrowserWindow({
    width: 440, height: 300, resizable: false, title: "Nova settings", alwaysOnTop: true,
    webPreferences: { preload: path.join(__dirname, "settings-preload.js"), contextIsolation: true, sandbox: true },
  });
  s.setMenu(null);
  s.loadFile(path.join(__dirname, "settings.html"));
}

function buildTray() {
  const icon = nativeImage.createFromPath(path.join(__dirname, "..", "assets", process.platform === "darwin" ? "trayTemplate.png" : "tray.png"));
  tray = new Tray(icon);
  tray.setToolTip("Nova");
  const menu = () =>
    Menu.buildFromTemplate([
      { label: `Show / hide Quick Chat  (${label(SHORTCUTS.toggle)})`, click: toggle },
      { label: `Screenshot to Quick Chat  (${label(SHORTCUTS.screenshot)})`, click: () => void screenshotToChat() },
      { type: "separator" },
      { label: "Reset window opacity", click: () => setOpacity(1) },
      { label: "Open Nova in browser", click: () => shell.openExternal(`${config.baseUrl}/chat`) },
      { label: "Settings…", click: openSettings },
      { label: "Start at login", type: "checkbox", checked: app.getLoginItemSettings().openAtLogin, click: (i) => app.setLoginItemSettings({ openAtLogin: i.checked }) },
      { type: "separator" },
      { label: "Quit Nova", click: quitForReal },
      { label: `Force quit Nova  (${label(SHORTCUTS.kill)})`, click: forceKill },
    ]);
  tray.setContextMenu(menu());
  tray.on("click", () => (process.platform === "darwin" ? tray.popUpContextMenu(menu()) : toggle()));
}

// ---- IPC (only from Nova's own origin; see preload.js) ----------------------------------
const fromNova = (e) => {
  try {
    return new URL(e.senderFrame.url).origin === origin();
  } catch {
    return false;
  }
};
ipcMain.handle("nova:capture", async (e) => {
  if (!fromNova(e)) throw new Error("forbidden");
  if (!(await ensureScreenPermission())) throw new Error("Screen Recording permission is needed.");
  return captureScreen();
});
ipcMain.on("nova:set-opacity", (e, v) => fromNova(e) && setOpacity(Number(v)));
ipcMain.handle("nova:get-opacity", (e) => (fromNova(e) ? config.opacity : 1));
ipcMain.handle("nova:shortcuts", () => ({ toggle: label(SHORTCUTS.toggle), screenshot: label(SHORTCUTS.screenshot), kill: label(SHORTCUTS.kill) }));
ipcMain.on("nova:hide", (e) => fromNova(e) && win?.hide());
ipcMain.on("nova:minimize", (e) => fromNova(e) && win?.minimize());
ipcMain.handle("nova:get-config", () => ({ baseUrl: config.baseUrl }));
ipcMain.handle("nova:set-base-url", (_e, url) => {
  const u = new URL(String(url));
  if (u.protocol !== "https:" && !["localhost", "127.0.0.1"].includes(u.hostname)) throw new Error("Use https (http only for localhost).");
  config.baseUrl = u.origin;
  saveConfig();
  win?.loadURL(`${config.baseUrl}/quick`);
  return { baseUrl: config.baseUrl };
});

// Automation hook for tests and support (`global.nova` in the main process).
global.nova = { toggle, screenshotToChat, captureScreen, window: () => win, setOpacity, quit: quitForReal, forceKill, captureAffinity: () => captureAffinity };

// ---- passkey gate (see passkey.js) --------------------------------------------------------
// Resolves true only for the right passkey. One attempt per launch: a wrong passkey closes Nova,
// and after passkey.MAX_TRIES wrong ones it stays locked on this device.
function askPasskey() {
  return new Promise((resolve) => {
    // Locked: the same window only says so (no passkey field) and closing it exits.
    const locked = passkey.readState(app).locked;
    const w = new BrowserWindow({
      width: 380, height: 290, resizable: false, minimizable: false, maximizable: false,
      fullscreenable: false, alwaysOnTop: true, show: false, title: locked ? "Nova is locked" : "Unlock Nova",
      webPreferences: { preload: path.join(__dirname, "passkey-preload.js"), contextIsolation: true, sandbox: true, nodeIntegration: false },
    });
    w.setMenu(null);
    w.setContentProtection(true);
    w.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    w.webContents.on("will-navigate", (e) => e.preventDefault());
    let done = false;
    let tried = false;
    const finish = (ok) => {
      if (done) return;
      done = true;
      ipcMain.removeHandler("nova:passkey");
      ipcMain.removeAllListeners("nova:passkey-cancel");
      if (!w.isDestroyed()) w.destroy();
      resolve(ok);
    };
    ipcMain.handle("nova:passkey", (e, value) => {
      if (e.sender !== w.webContents) throw new Error("forbidden");
      if (locked) return { ok: false, left: 0, locked: true };
      if (tried) return { ok: false, left: 0, locked: false };
      tried = true;
      const r = passkey.attempt(app, value);
      setTimeout(() => finish(r.ok), r.ok ? 250 : 2200); // let the message be read, then close
      return r;
    });
    ipcMain.on("nova:passkey-cancel", (e) => e.sender === w.webContents && (!tried || locked) && finish(false));
    w.on("closed", () => finish(false)); // closed without the passkey: Nova doesn't open
    w.loadFile(path.join(__dirname, "passkey.html"), locked ? { query: { locked: "1" } } : undefined);
    w.once("ready-to-show", () => {
      w.show();
      if (process.platform === "darwin") app.focus({ steal: true });
      w.focus();
    });
  });
}

// ---- lifecycle ---------------------------------------------------------------------------
// Test hook only; installed builds ignore it so it can't be used to dodge the passkey lock.
if (process.env.NOVA_USER_DATA && !app.isPackaged) app.setPath("userData", process.env.NOVA_USER_DATA);
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", showWindow);
  app.whenReady().then(async () => {
    config = loadConfig();
    // Opened straight from the .dmg? Then ejecting the installer would kill Nova (and the login
    // item would point at a vanished disk). Offer to move into Applications and relaunch.
    if (process.platform === "darwin" && app.isPackaged && !app.isInApplicationsFolder()) {
      const choice = dialog.showMessageBoxSync({
        type: "question",
        message: "Move Nova to your Applications folder?",
        detail: "Nova keeps running in the background so Option + / works any time. It needs to live in Applications to keep working after you close the installer.",
        buttons: ["Move to Applications", "Not now"],
        defaultId: 0,
        cancelId: 1,
      });
      if (choice === 0) {
        // Let this copy really quit and hand the single-instance lock to the relaunched one.
        quitting = true;
        app.releaseSingleInstanceLock();
        try {
          if (app.moveToApplicationsFolder()) return; // quits and relaunches from /Applications
          quitting = false;
        } catch (err) {
          quitting = false;
          dialog.showErrorBox("Couldn't move Nova", `${err?.message ?? err}\n\nDrag Nova into Applications from the installer window instead.`);
        }
      }
    }
    if (!app.hasSingleInstanceLock() && !app.requestSingleInstanceLock()) return app.quit();
    if (!(await askPasskey())) {
      quitting = true;
      return app.exit(0);
    }
    unlocked = true;
    if (process.platform === "darwin") app.dock?.hide(); // tray app, like a menu-bar utility
    const firstRun = !fs.existsSync(cfgPath());
    if (firstRun) {
      saveConfig();
      if (!process.env.NOVA_NO_LOGIN_ITEM) app.setLoginItemSettings({ openAtLogin: true });
    }
    buildTray();
    registerShortcuts();
    powerMonitor.on("shutdown", quitForReal); // never block shutdown, restart or logout
    createWindow({ show: firstRun || !!process.env.NOVA_SHOW });
    updatePeek();
  });
  app.on("will-quit", () => globalShortcut.unregisterAll());
  app.on("before-quit", (e) => {
    if (quitting || !unlocked) return; // (⌘Q on the passkey window just quits)
    e.preventDefault(); // ⌘Q / "Quit" from the window: keep running in the background
    win?.hide();
  });
  app.on("window-all-closed", (e) => e.preventDefault()); // keep running in the tray
}

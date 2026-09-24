// Nova Quick Chat: a floating, movable window running the Nova /quick page (docs/27 §17b).
// It is an independent browser window, so it survives closing the Nova website tab, and it
// can be dragged anywhere on screen. Position/size and the last chat are remembered.

const DEFAULTS = { baseUrl: "http://localhost:3000" };
const SIZE = { width: 440, height: 680 };

async function settings() {
  const s = await chrome.storage.sync.get(DEFAULTS);
  return { baseUrl: String(s.baseUrl || DEFAULTS.baseUrl).replace(/\/+$/, "") };
}

async function state() {
  return chrome.storage.local.get({ windowId: null, bounds: null });
}

async function existingWindow() {
  const { windowId } = await state();
  if (windowId == null) return null;
  try {
    return await chrome.windows.get(windowId);
  } catch {
    await chrome.storage.local.set({ windowId: null });
    return null;
  }
}

async function toggle() {
  const win = await existingWindow();
  if (win) {
    // Focused → hide (minimize, keeps the chat); hidden/behind → bring to front.
    if (win.focused && win.state !== "minimized") {
      await chrome.windows.update(win.id, { state: "minimized" });
    } else {
      await chrome.windows.update(win.id, { state: "normal", focused: true, drawAttention: false });
    }
    return;
  }
  const { baseUrl } = await settings();
  const { bounds } = await state();
  const created = await chrome.windows.create({
    url: `${baseUrl}/quick`,
    type: "popup", // no tab strip or address bar: a compact chat window
    focused: true,
    width: bounds?.width ?? SIZE.width,
    height: bounds?.height ?? SIZE.height,
    ...(bounds ? { left: bounds.left, top: bounds.top } : {}),
  });
  await chrome.storage.local.set({ windowId: created.id });
}

// Reachable from the service-worker console (and E2E) to open/hide the window directly.
self.toggleQuickChat = toggle;

chrome.commands.onCommand.addListener((command) => {
  if (command === "toggle-quick-chat") void toggle();
});

chrome.action.onClicked.addListener(() => void toggle());

// Remember where the user put the window and how big they made it.
chrome.windows.onBoundsChanged.addListener(async (win) => {
  const { windowId } = await state();
  if (win.id !== windowId || win.state !== "normal") return;
  await chrome.storage.local.set({ bounds: { left: win.left, top: win.top, width: win.width, height: win.height } });
});

chrome.windows.onRemoved.addListener(async (id) => {
  const { windowId } = await state();
  if (id === windowId) await chrome.storage.local.set({ windowId: null });
});

chrome.runtime.onInstalled.addListener(async ({ reason }) => {
  if (reason === "install") await chrome.runtime.openOptionsPage();
});

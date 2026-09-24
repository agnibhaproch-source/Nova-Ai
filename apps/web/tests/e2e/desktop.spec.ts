import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";

import { _electron as electron, expect, test } from "@playwright/test";

const DESKTOP = path.resolve(__dirname, "../../../desktop");
const STATE = "playwright/.auth/user.json";
const PASSKEY = "56748";

const electronPath = () => createRequire(__filename)(path.join(DESKTOP, "node_modules/electron")) as unknown as string;
// Editors built on Electron (VS Code) export ELECTRON_RUN_AS_NODE; it must not leak in.
const cleanEnv = () => Object.fromEntries(Object.entries(process.env).filter(([k]) => k !== "ELECTRON_RUN_AS_NODE")) as Record<string, string>;
const launch = (baseURL: string, userData: string) =>
  electron.launch({
    executablePath: electronPath(),
    args: [DESKTOP],
    env: { ...cleanEnv(), NOVA_URL: baseURL, NOVA_USER_DATA: userData, NOVA_NO_LOGIN_ITEM: "1", NOVA_SHOW: "1" },
  });
type App = Awaited<ReturnType<typeof launch>>;

/** Types into the passkey window that opens first; resolves once the app exits (wrong passkey). */
async function enterPasskey(app: App, value: string) {
  const gate = await app.firstWindow();
  await expect(gate).toHaveTitle("Unlock Nova");
  await gate.getByLabel("Passkey").fill(value);
  await gate.getByRole("button", { name: "Unlock" }).click();
  return gate;
}

/** Locked: only a "locked on this device" window, no passkey field; closing it exits Nova. */
async function expectLocked(baseURL: string, userData: string) {
  const app = await launch(baseURL, userData);
  const exited = new Promise((r) => app.process().once("exit", r));
  const gate = await app.firstWindow();
  await expect(gate).toHaveTitle("Nova is locked");
  await expect(gate.getByRole("heading")).toHaveText("Nova is locked on this device");
  await expect(gate.getByLabel("Passkey")).toHaveCount(0);
  expect(await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().length)).toBe(1);
  await gate.getByRole("button", { name: "Close" }).click();
  await exited;
}

test("desktop app: asks for the passkey on every launch and locks the device after 3 wrong ones", async ({ baseURL, isMobile }) => {
  test.skip(isMobile, "desktop only");
  test.setTimeout(120_000);
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), "nova-lock-"));
  for (const left of [2, 1]) {
    const app = await launch(baseURL!, userData);
    const exited = new Promise((r) => app.process().once("exit", r));
    const gate = await enterPasskey(app, "11111");
    await expect(gate.getByRole("status")).toHaveText(`Wrong passkey. ${left} ${left === 1 ? "try" : "tries"} left. Nova will close.`);
    await exited; // a wrong passkey never opens Nova
    expect(app.process().exitCode).toBe(0);
  }
  // Closing the passkey window without a passkey doesn't open Nova (and doesn't use a try).
  {
    const app = await launch(baseURL!, userData);
    const exited = new Promise((r) => app.process().once("exit", r));
    const gate = await app.firstWindow();
    await gate.getByRole("button", { name: "Quit" }).click();
    await exited;
  }
  // Third wrong passkey: locked for good; even the right passkey can't open it any more.
  {
    const app = await launch(baseURL!, userData);
    const exited = new Promise((r) => app.process().once("exit", r));
    const gate = await enterPasskey(app, "22222");
    await expect(gate.getByRole("status")).toHaveText("Wrong passkey. Nova is now locked on this device.");
    await exited;
  }
  await expectLocked(baseURL!, userData);
  const guard = JSON.parse(JSON.parse(fs.readFileSync(path.join(userData, ".guard"), "utf8")).body);
  expect(guard).toMatchObject({ fails: 3, locked: true });
  // Tampering with the record doesn't unlock it: an edited record counts as locked.
  fs.writeFileSync(path.join(userData, ".guard"), JSON.stringify({ body: JSON.stringify({ fails: 0, locked: false }), mac: "00" }));
  fs.rmSync(path.join(userData, ".guard2"));
  await expectLocked(baseURL!, userData);
});

test("desktop app: floating always-on-top window, global toggle, opacity, screenshots into Quick Chat", async ({ baseURL, isMobile }) => {
  test.skip(isMobile, "desktop only");
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), "nova-desktop-"));
  const app = await launch(baseURL!, userData);
  try {
    // Nothing opens before the passkey.
    expect(await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().length)).toBeLessThanOrEqual(1);
    const nextWindow = app.waitForEvent("window");
    await enterPasskey(app, PASSKEY);
    // Sign the app's persistent session in with the E2E account.
    const cookies = JSON.parse(fs.readFileSync(STATE, "utf8")).cookies;
    await app.evaluate(async ({ session }, { cookies, url }) => {
      const s = session.fromPartition("persist:nova");
      for (const c of cookies) await s.cookies.set({ url, name: c.name, value: c.value, path: c.path, httpOnly: c.httpOnly, secure: c.secure, sameSite: "lax" });
    }, { cookies, url: baseURL! });
    const page = await nextWindow;
    await page.goto(`${baseURL}/login?next=%2Fquick`); // signed in → straight to Quick Chat
    await page.waitForURL(/\/quick/);
    await expect(page.getByRole("textbox", { name: "Message Nova" })).toBeVisible();

    const winState = () =>
      app.evaluate(() => {
        const w = (global as unknown as { nova: { window: () => Electron.BrowserWindow } }).nova.window();
        return { visible: w.isVisible(), onTop: w.isAlwaysOnTop(), opacity: w.getOpacity() };
      });
    expect((await winState()).onTop).toBe(true);
    // The window is excluded from screen capture by the OS API itself (SetWindowDisplayAffinity on
    // Windows, NSWindow.sharingType on macOS), confirmed by reading the setting back.
    if (process.platform === "darwin" || process.platform === "win32") {
      expect(await app.evaluate(() => (global as unknown as { nova: { captureAffinity: () => string } }).nova.captureAffinity())).toBe("exclude");
    }
    // The system-wide shortcuts (toggle, screenshot, force quit) are registered with the OS.
    expect(
      await app.evaluate(({ globalShortcut }) => ["Alt+/", "Alt+\\", "Alt+Shift+Q"].map((k) => globalShortcut.isRegistered(k))),
    ).toEqual([true, true, true]);

    // Global shortcut action: hide, then show again.
    await app.evaluate(() => (global as unknown as { nova: { toggle: () => void } }).nova.toggle());
    await expect.poll(async () => (await winState()).visible).toBe(false);
    await app.evaluate(() => (global as unknown as { nova: { toggle: () => void } }).nova.toggle());
    await expect.poll(async () => (await winState()).visible).toBe(true);

    // Opacity from Quick Chat settings drives the native window opacity.
    await page.getByRole("button", { name: "Settings" }).click();
    await page.getByLabel("Opacity").fill("40");
    await expect.poll(async () => (await winState()).opacity).toBeCloseTo(0.4, 2);
    await page.getByLabel("Opacity").fill("100");
    await page.getByRole("button", { name: "Back to chat" }).click();

    // Screenshot delivered by the main process (what Alt+\ does) lands in the composer,
    // even while the window is hidden.
    await app.evaluate(() => (global as unknown as { nova: { toggle: () => void } }).nova.toggle());
    await app.evaluate(({ nativeImage }) => {
      const img = nativeImage.createFromBuffer(Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEklEQVR4nGP4z8CAFTEMLQkAyrN/gV08/q8AAAAASUVORK5CYII=", "base64"));
      const w = (global as unknown as { nova: { window: () => Electron.BrowserWindow } }).nova.window();
      w.webContents.send("nova:screenshot", img.toDataURL());
    });
    await app.evaluate(() => (global as unknown as { nova: { toggle: () => void } }).nova.toggle());
    await expect(page.getByText(/^screenshot-.*\.png$/)).toHaveCount(1, { timeout: 15_000 });

    // Like ChatGPT: closing the window and ⌘Q only send Nova to the background; the shortcut
    // brings the popup back.
    type G = { nova: { toggle: () => void; window: () => Electron.BrowserWindow } };
    await app.evaluate(() => (global as unknown as G).nova.window().close());
    await expect.poll(async () => (await winState()).visible).toBe(false);
    await app.evaluate(({ app: a }) => a.quit());
    await new Promise((r) => setTimeout(r, 500));
    expect(app.process().exitCode).toBeNull(); // still running
    await app.evaluate(() => (global as unknown as G).nova.toggle());
    await expect.poll(async () => (await winState()).visible).toBe(true);
    await expect(page.getByRole("textbox", { name: "Message Nova" })).toBeVisible();

    // Real capture works where the OS allows it (macOS needs Screen Recording permission).
    if (process.platform !== "darwin") {
      const shot = await app.evaluate(() => (global as unknown as { nova: { captureScreen: () => Promise<string> } }).nova.captureScreen());
      expect(shot.startsWith("data:image/png;base64,")).toBe(true);
    }

    // Option/Alt+Shift+Q force-kills the entire app, not just the popup.
    const killed = new Promise((r) => app.process().once("exit", r));
    await app.evaluate(() => (global as unknown as { nova: { forceKill: () => void } }).nova.forceKill()).catch(() => {});
    await killed;
    expect(app.process().exitCode).toBe(0);
  } finally {
    // Otherwise only the tray's "Quit Nova" really exits.
    const proc = (() => {
      try {
        return app.process();
      } catch {
        return null; // the app already went away; the real failure is reported above
      }
    })();
    if (!proc || proc.exitCode !== null) return;
    const exited = new Promise((r) => app.process().once("exit", r));
    await app.evaluate(() => (global as unknown as { nova: { quit: () => void } }).nova.quit()).catch(() => {});
    await exited;
  }
});

import fs from "node:fs";
import path from "node:path";

import { chromium, expect, test } from "@playwright/test";

import { GROQ_KEY } from "./helpers";

const EXT = path.resolve(__dirname, "../../../extension");
const STATE = "playwright/.auth/user.json";

test("extension window floats on its own and keeps chatting after the Nova tab closes", async ({ baseURL, isMobile }, info) => {
  test.skip(isMobile, "desktop browsers only");
  const ctx = await chromium.launchPersistentContext(info.outputPath("profile"), {
    channel: "chromium",
    args: [`--disable-extensions-except=${EXT}`, `--load-extension=${EXT}`],
  });
  try {
    const cookies = JSON.parse(fs.readFileSync(STATE, "utf8")).cookies;
    await ctx.addCookies(cookies);
    const sw = ctx.serviceWorkers()[0] ?? (await ctx.waitForEvent("serviceworker"));
    await sw.evaluate((url) => chrome.storage.sync.set({ baseUrl: url }), baseURL!);

    // The "website" tab.
    const site = await ctx.newPage(); // (the extension opens its settings page on install)
    await site.goto(`${baseURL}/chat`);

    // Shortcut / toolbar action → separate floating window with /quick.
    const opened = ctx.waitForEvent("page");
    await sw.evaluate(() => (self as unknown as { toggleQuickChat: () => Promise<void> }).toggleQuickChat());
    const quick = await opened;
    await quick.waitForURL(/\/quick/);

    // Close every Nova website tab: the Quick Chat window must survive.
    for (const p of ctx.pages()) if (p !== quick) await p.close();
    expect(quick.isClosed()).toBe(false);

    await quick.getByPlaceholder(/Paste your Groq API key/).fill(GROQ_KEY);
    await quick.getByRole("textbox", { name: "Message Nova" }).fill("Hello from the extension window");
    await quick.getByRole("button", { name: "Send message" }).click();
    await expect(quick.getByRole("log")).toContainText("running against the local Groq stub", { timeout: 20_000 });

    // It's a real popup window (no tab strip), and toggling again hides then restores it.
    const win = await sw.evaluate(async () => {
      const { windowId } = await chrome.storage.local.get("windowId");
      return chrome.windows.get(windowId as number);
    });
    expect(win.type).toBe("popup");

    // Reopening resumes the same chat.
    await quick.reload();
    await expect(quick.getByRole("log")).toContainText("Hello from the extension window");
  } finally {
    await ctx.close();
  }
});

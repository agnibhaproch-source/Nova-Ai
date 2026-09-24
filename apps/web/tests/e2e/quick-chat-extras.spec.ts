import { expect, type Page, test } from "@playwright/test";

import { GROQ_KEY } from "./helpers";

/** Replace the browser's screen picker with a canvas stream, and record whether the Quick Chat
 * window was visible at the moment the frame was grabbed. */
async function fakeScreen(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as Record<string, unknown>;
    w.__grabs = [] as string[];
    navigator.mediaDevices.getDisplayMedia = async () => {
      const c = document.createElement("canvas");
      c.width = 640;
      c.height = 360;
      const ctx = c.getContext("2d")!;
      const paint = () => {
        ctx.fillStyle = "#1e1e2e";
        ctx.fillRect(0, 0, 640, 360);
        ctx.fillStyle = "#fff";
        ctx.font = "28px monospace";
        ctx.fillText("def add(a, b): return a + b", 20, 180);
      };
      paint();
      setInterval(paint, 100);
      return c.captureStream(10);
    };
    const orig = CanvasRenderingContext2D.prototype.drawImage;
    CanvasRenderingContext2D.prototype.drawImage = function (this: CanvasRenderingContext2D, ...a: unknown[]) {
      if (a[0] instanceof HTMLVideoElement) {
        const d = document.querySelector('[role=dialog][aria-label="Quick Chat"]');
        (w.__grabs as string[]).push(d ? getComputedStyle(d).visibility : "absent");
      }
      return (orig as (...x: unknown[]) => void).apply(this, a);
    } as typeof orig;
  });
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    for (const k of ["nova-quick-chat-conversation", "nova-quick-chat-opacity", "nova-quick-chat-pos"]) localStorage.removeItem(k);
  });
});

test("Quick Chat has settings: opacity 100→0 and every website settings section", async ({ page, isMobile }) => {
  await page.goto("/settings/general");
  await page.locator("body").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("/");
  const quick = page.getByRole("dialog", { name: "Quick Chat" });
  await quick.getByRole("button", { name: "Settings" }).click();

  const slider = quick.getByLabel("Opacity");
  await slider.fill("40");
  await expect(quick).toHaveCSS("opacity", "0.4");
  await slider.fill("0");
  await expect(quick.getByText("0%", { exact: true })).toBeAttached();
  await page.mouse.move(1, 1); // away from the window: fully transparent
  await expect(quick).toHaveCSS("opacity", "0");
  if (!isMobile) {
    const box = (await quick.boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + 20); // hovering reveals it at 20%
    await expect(quick).toHaveCSS("opacity", "0.2");
  }

  await slider.fill("100");
  for (const tab of ["General", "Memory", "Billing", "API keys", "Data controls"]) {
    await quick.getByRole("button", { name: tab, exact: true }).click();
    await expect(quick.getByRole("heading").first()).toBeVisible();
  }
  await quick.getByRole("button", { name: "Back to chat" }).click();
  await expect(quick.getByRole("textbox", { name: "Message Nova" })).toBeVisible();
});

test("\\ takes screenshots while Quick Chat is closed, without capturing it, and they're sent for analysis", async ({ page, isMobile }) => {
  test.skip(isMobile, "no screen capture on mobile browsers");
  await fakeScreen(page);
  await page.goto("/settings/general");
  await page.locator("body").click({ position: { x: 5, y: 5 } });
  const quick = page.getByRole("dialog", { name: "Quick Chat" });

  // Closed: "\" captures and queues; the window stays closed.
  await page.keyboard.press("\\");
  await expect(page.getByText(/Screenshot added to Quick Chat/)).toBeVisible();
  await expect(quick).toHaveCount(0);
  await page.keyboard.press("\\");
  await expect(page.getByText(/2 waiting/)).toBeVisible();

  // Open: "\" again — the window is hidden in the grabbed frame.
  await page.keyboard.press("/");
  await expect(quick).toBeVisible();
  await page.locator("body").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("\\");
  await expect(quick.getByText(/^screenshot-.*\.png$/)).toHaveCount(3, { timeout: 15_000 });
  const grabs = await page.evaluate(() => (window as unknown as { __grabs: string[] }).__grabs);
  expect(grabs).toEqual(["absent", "absent", "hidden"]);
  await expect(quick).toBeVisible();

  // Send just the screenshots (no text): Send enables once they're uploaded, the server
  // processes them and the vision model answers (via the Groq stub).
  await quick.getByPlaceholder(/Paste your Groq API key/).fill(GROQ_KEY);
  await expect(quick.getByRole("textbox", { name: "Message Nova" })).toHaveValue("");
  const send = quick.getByRole("button", { name: "Send message" });
  await expect(send).toBeEnabled({ timeout: 30_000 }); // waits for uploads + processing
  await send.click();
  await expect(quick.getByRole("log")).toContainText("running against the local Groq stub", { timeout: 30_000 });
  await expect(quick.getByRole("log").locator("img")).toHaveCount(3);
});

test("camera button in the composer attaches a screenshot", async ({ page, isMobile }) => {
  test.skip(isMobile, "no screen capture on mobile browsers");
  await fakeScreen(page);
  await page.goto("/chat");
  await page.getByRole("button", { name: "Take a screenshot" }).click();
  await expect(page.getByText(/^screenshot-.*\.png$/)).toHaveCount(1, { timeout: 15_000 });
});

import { expect, test } from "@playwright/test";

import { GROQ_KEY } from "./helpers";

test("/ opens Quick Chat over any page; it chats without leaving the page", async ({ page }) => {
  await page.goto("/settings/general");
  await page.locator("body").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("/");
  const quick = page.getByRole("dialog", { name: "Quick Chat" });
  await expect(quick).toBeVisible();

  await quick.getByPlaceholder(/Paste your Groq API key/).fill(GROQ_KEY);
  await quick.getByRole("textbox", { name: "Message Nova" }).fill("Quick question");
  await quick.getByRole("button", { name: "Send message" }).click();
  await expect(quick.getByRole("log")).toContainText("running against the local Groq stub", { timeout: 20_000 });
  await expect(page).toHaveURL(/\/settings\/general$/); // main page untouched
  await expect(quick.getByRole("button", { name: "Regenerate" })).toBeVisible(); // reply finished

  await quick.getByRole("textbox", { name: "Message Nova" }).click();
  await page.keyboard.press("Escape");
  await expect(quick).toBeHidden();
  await page.keyboard.press("/");
  await expect(quick.getByRole("log")).toContainText("Quick question"); // same chat reopens

  // Every chat is remembered: start a new one, then pick the earlier chat from the history list.
  const earlier = await page.evaluate(() => localStorage.getItem("nova-quick-chat-conversation"));
  expect(earlier).toBeTruthy();
  await quick.getByRole("button", { name: "New quick chat" }).click();
  await expect(quick.getByRole("log")).toHaveCount(0);
  await quick.getByRole("button", { name: "Chat history" }).click();
  const history = quick.getByRole("navigation", { name: "Chat history" });
  await history.locator(`[data-conversation-id="${earlier}"]`).click();
  await expect(quick.getByRole("log")).toContainText("Quick question");
});

test("files can be dragged and dropped anywhere on the chat", async ({ page }) => {
  await page.goto("/chat");
  await expect(page.getByRole("button", { name: "Attach files" })).toBeVisible(); // attachments ready
  const drop = async (type: "dragenter" | "drop") =>
    page.locator("[data-chat-view]").first().evaluate((view, type) => {
      const dt = new DataTransfer();
      dt.items.add(new File(["# Notes\n\nDropped file"], "notes.md", { type: "text/markdown" }));
      // Dropped on the message area (the view's first child), not on the composer.
      const target = view.firstElementChild ?? view;
      target.dispatchEvent(new DragEvent(type, { dataTransfer: dt, bubbles: true, cancelable: true }));
    }, type);
  await drop("dragenter");
  await expect(page.getByText("Drop files to attach")).toBeVisible();
  await drop("drop");
  await expect(page.getByText("Drop files to attach")).toBeHidden();
  await expect(page.getByText("notes.md")).toBeVisible();
});

test("/ in the empty main composer opens Quick Chat; typed text is left alone", async ({ page }) => {
  await page.goto("/chat");
  const main = page.getByRole("textbox", { name: "Message Nova" });
  await main.click();
  await page.keyboard.press("/");
  await expect(page.getByRole("dialog", { name: "Quick Chat" })).toBeVisible();
  await page.getByRole("button", { name: "Close (Esc)" }).click();

  await main.fill("a/b");
  await expect(main).toHaveValue("a/b");
  await expect(page.getByRole("dialog", { name: "Quick Chat" })).toBeHidden();
});

test("pop-out window renders Quick Chat on its own", async ({ page }) => {
  await page.goto("/quick");
  await expect(page.getByText("Quick Chat", { exact: true })).toHaveCount(0); // no header bar
  await expect(page.getByRole("button", { name: "Settings" })).toBeAttached(); // controls show on hover
  await expect(page.getByRole("navigation")).toHaveCount(0); // no sidebar
  await expect(page.getByRole("textbox", { name: "Message Nova" })).toBeVisible();
});

test("Quick Chat floats and can be dragged anywhere, stays on screen, and remembers its spot", async ({ page, isMobile }) => {
  await page.goto("/settings/general");
  await page.evaluate(() => localStorage.removeItem("nova-quick-chat-pos"));
  await page.locator("body").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("/");
  const quick = page.getByRole("dialog", { name: "Quick Chat" });
  const handle = quick.getByLabel(/Move Quick Chat/);
  const vp = page.viewportSize()!;
  const start = (await quick.boundingBox())!;
  expect(start.x + start.width).toBeGreaterThan(vp.width - 40); // default: bottom-right

  // Drag to the top-left corner.
  const h = (await handle.boundingBox())!;
  const grab = { x: h.x + 60, y: h.y + h.height / 2 };
  await page.mouse.move(grab.x, grab.y);
  await page.mouse.down();
  await page.mouse.move(grab.x - (start.x - 30), grab.y - (start.y - 30), { steps: 8 });
  await page.mouse.up();
  const moved = (await quick.boundingBox())!;
  expect(moved.x).toBeLessThan(40);
  expect(moved.y).toBeLessThan(40);

  // Dragging past the edge is clamped: the window never leaves the viewport.
  const h2 = (await handle.boundingBox())!;
  await page.mouse.move(h2.x + 60, h2.y + 10);
  await page.mouse.down();
  await page.mouse.move(-500, -500, { steps: 5 });
  await page.mouse.up();
  const clamped = (await quick.boundingBox())!;
  expect(clamped.x).toBeGreaterThanOrEqual(0);
  expect(clamped.y).toBeGreaterThanOrEqual(0);

  // Keyboard: arrow keys move it too.
  await handle.focus();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowDown");
  const nudged = (await quick.boundingBox())!;
  if (!isMobile) expect(nudged.x).toBeGreaterThan(clamped.x); // on phones it spans the width
  expect(nudged.y).toBeGreaterThan(clamped.y);

  // Position survives reload.
  await page.reload();
  await page.locator("body").click({ position: { x: vp.width - 5, y: vp.height - 5 } });
  await page.keyboard.press("/");
  const reopened = (await quick.boundingBox())!;
  expect(Math.abs(reopened.x - nudged.x)).toBeLessThan(2);
  expect(Math.abs(reopened.y - nudged.y)).toBeLessThan(2);

  // Double-click the title bar snaps it back to bottom-right.
  if (!isMobile) {
    await handle.dblclick({ position: { x: 60, y: 10 } });
    const reset = (await quick.boundingBox())!;
    expect(reset.x + reset.width).toBeGreaterThan(vp.width - 40);
  }
});

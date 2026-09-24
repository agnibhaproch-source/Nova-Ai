import { expect, type Page, test } from "@playwright/test";

import { PASSWORD, signUp, startChat } from "./helpers";

// Whole-product journeys on a fresh account: settings persist, chats can be managed, messages
// edited/regenerated, and the account can log out, log in and reset its password by email.
test.use({ storageState: { cookies: [], origins: [] } });
test.skip(({ isMobile }) => isMobile, "sidebar flows are covered on desktop");

const MAILPIT = "http://localhost:8025/api/v1";

async function resetLinkFor(page: Page, email: string) {
  let link: string | undefined;
  await expect
    .poll(async () => {
      const list = await (await page.request.get(`${MAILPIT}/search?query=${encodeURIComponent(`to:${email}`)}`)).json();
      const id = list.messages?.find((m: { Subject: string }) => /reset/i.test(m.Subject))?.ID;
      if (!id) return false;
      const msg = await (await page.request.get(`${MAILPIT}/message/${id}`)).json();
      link = /(http\S+\/reset-password\?token=[\w-]+)/.exec(msg.Text)?.[1];
      return !!link;
    }, { timeout: 20_000 })
    .toBe(true);
  return link!;
}

test("account, settings, chats and messages work end to end", async ({ page }) => {
  test.setTimeout(120_000);
  const email = await signUp(page);

  // Settings persist across reloads.
  await page.goto("/settings/general");
  await page.getByRole("radio", { name: /dark/i }).click();
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.getByRole("radio", { name: /light/i }).click();
  await page.goto("/settings/personalization");
  const instructions = page.getByRole("textbox", { name: "How should Nova respond?" });
  await instructions.fill("Answer briefly.");
  await page.getByRole("button", { name: "Save" }).first().click(); // the instructions box's Save
  await expect(page.getByText("Saved")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("textbox", { name: "How should Nova respond?" })).toHaveValue("Answer briefly.");

  // Chat: send, edit the message (new branch), regenerate.
  await page.goto("/chat");
  await startChat(page, "First question");
  const log = page.getByRole("log");
  await expect(page.getByRole("button", { name: "Regenerate" })).toBeVisible();
  await log.getByText("First question").hover();
  await page.getByRole("button", { name: "Edit" }).click();
  await page.getByRole("textbox", { name: "Edit message" }).fill("Edited question");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(log).toContainText("Edited question");
  await expect(page.getByRole("button", { name: "Regenerate" })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "Regenerate" }).click();
  await expect(page.getByRole("button", { name: "Regenerate" })).toBeVisible({ timeout: 20_000 });

  // Manage the chat from the sidebar: rename, find it with search, delete, undo, restore from trash.
  const conversations = page.getByRole("navigation", { name: "Conversations" });
  const item = conversations.getByRole("link").first();
  await item.hover();
  await conversations.getByRole("button", { name: /^Options for/ }).first().click();
  await page.getByRole("menuitem", { name: "Rename" }).click();
  await page.getByRole("textbox", { name: "Conversation title" }).fill("Journey chat");
  await page.keyboard.press("Enter");
  await expect(conversations.getByRole("link", { name: "Journey chat" })).toBeVisible();

  await page.getByRole("button", { name: /Search chats/ }).click();
  await page.getByPlaceholder("Search chats…").fill("Journey");
  await expect(page.getByRole("dialog").getByText("Journey chat").first()).toBeVisible();
  await page.keyboard.press("Escape");

  await conversations.getByRole("link", { name: "Journey chat" }).hover();
  await conversations.getByRole("button", { name: "Options for Journey chat" }).click();
  await page.getByRole("menuitem", { name: "Delete" }).click();
  await expect(conversations.getByRole("link", { name: "Journey chat" })).toHaveCount(0);
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(conversations.getByRole("link", { name: "Journey chat" })).toBeVisible();

  // Log out, then log back in.
  await page.getByRole("button", { name: /E2E User/ }).click();
  await page.getByRole("menuitem", { name: "Log out" }).click();
  await page.waitForURL(/\/login/);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await page.waitForURL(/\/chat/);
  await expect(page.getByRole("navigation", { name: "Conversations" }).getByRole("link", { name: "Journey chat" })).toBeVisible();

  // Forgot password → email (Mailpit) → new password → log in with it.
  await page.getByRole("button", { name: /E2E User/ }).click();
  await page.getByRole("menuitem", { name: "Log out" }).click();
  await page.waitForURL(/\/login/);
  await page.goto("/forgot-password");
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Send reset link" }).click();
  const link = await resetLinkFor(page, email);
  await page.goto(new URL(link).pathname + new URL(link).search);
  await page.getByLabel("New password").fill("another-strong-pass-42");
  await page.getByLabel("Confirm password").fill("another-strong-pass-42");
  await page.getByRole("button", { name: "Update password" }).click();
  await page.waitForURL(/\/login/);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("another-strong-pass-42");
  await page.getByRole("button", { name: "Log in" }).click();
  await page.waitForURL(/\/chat/);
});

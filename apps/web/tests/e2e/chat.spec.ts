import { expect, test } from "@playwright/test";

import { startChat } from "./helpers";

test("new chat needs a Groq key, then streams a reply", async ({ page }) => {
  await page.goto("/chat");
  await page.getByRole("textbox", { name: "Message Nova" }).fill("Hi there");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText(/Paste your Groq API key \(starts with gsk_\)/)).toBeVisible();
  await expect(page).toHaveURL(/\/chat$/);

  await startChat(page, "Hi there");
  await expect(page.getByRole("button", { name: "Regenerate" })).toBeVisible();
  // The key is never readable again from the browser.
  const status = await page.evaluate(async () => {
    const id = location.pathname.split("/").pop();
    return (await fetch(`/api/v1/conversations/${id}/groq-key`)).json();
  });
  expect(status.data.configured).toBe(true);
  expect(JSON.stringify(status)).not.toContain("gsk_");
});

test("settings sections render", async ({ page }) => {
  for (const [path, heading] of [
    ["/settings/memory", "Memory"],
    ["/settings/files", "Files"],
    ["/settings/billing", "Plan"],
    ["/settings/api-keys", "API keys"],
  ] as const) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
  }
});

test("pricing page lists plans", async ({ page }) => {
  await page.goto("/pricing");
  await expect(page.getByRole("heading", { name: "Simple plans" })).toBeVisible();
  for (const plan of ["Free", "Plus", "Pro"]) await expect(page.getByRole("heading", { name: plan, exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Current plan" })).toBeVisible();
});

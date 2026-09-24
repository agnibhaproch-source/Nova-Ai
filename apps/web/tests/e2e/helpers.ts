import { expect, type Page } from "@playwright/test";

export const PASSWORD = "correct-horse-battery-9";
export const GROQ_KEY = "gsk_e2e_test_key_not_real_000000";

export async function signUp(page: Page) {
  const email = `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
  await page.goto("/signup");
  await page.getByLabel("Name").fill("E2E User");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create account" }).click();
  await page.waitForURL("**/onboarding");
  await page.getByRole("button", { name: "Skip" }).click();
  await page.waitForURL("**/chat");
  return email;
}

export async function startChat(page: Page, message: string) {
  await page.getByPlaceholder(/Paste your Groq API key/).fill(GROQ_KEY);
  await page.getByRole("textbox", { name: "Message Nova" }).fill(message);
  await page.getByRole("button", { name: "Send message" }).click();
  await page.waitForURL(/\/c\/[0-9a-f-]{36}/);
  await expect(page.getByRole("log")).toContainText("running against the local Groq stub", { timeout: 20_000 });
}

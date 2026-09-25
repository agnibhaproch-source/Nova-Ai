import { expect, type Page, test } from "@playwright/test";

// Visits every route and fails on uncaught errors, console errors, 5xx responses or a blank
// page. Signed-in routes use the E2E account (a pro user, not an admin).
const PUBLIC = ["/", "/download", "/login", "/signup", "/forgot-password", "/reset-password?token=invalid-token-xyz"];
const APP = [
  "/chat",
  "/quick",
  "/onboarding",
  "/settings",
  ...["general", "profile", "personalization", "memory", "files", "data", "security", "usage", "api-keys"].map((s) => `/settings/${s}`),
];
const ADMIN = ["/admin", "/admin/users", "/admin/usage", "/admin/health"];

function watch(page: Page) {
  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    // Dev-only React notice about the deliberate pre-paint theme script (see app/layout.tsx).
    if (m.type() === "error" && !m.text().startsWith("Encountered a script tag")) problems.push(`console: ${m.text()}`);
  });
  page.on("response", (r) => {
    if (r.status() >= 500) problems.push(`HTTP ${r.status()} ${r.url()}`);
  });
  return problems;
}

async function visit(page: Page, path: string) {
  const problems = watch(page);
  const res = await page.goto(path);
  expect(res?.status(), path).toBeLessThan(500);
  await page.waitForLoadState("networkidle");
  await expect(page.locator("h1, h2, [role=heading], textarea").first(), `${path} renders content`).toBeVisible();
  expect(problems, `${path} has no errors`).toEqual([]);
}

test.describe("signed out", () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  for (const path of PUBLIC) test(`public page ${path}`, async ({ page }) => visit(page, path));
  test("app pages send you to login", async ({ page }) => {
    await page.goto("/chat");
    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe("signed in", () => {
  for (const path of APP) test(`app page ${path}`, async ({ page }) => visit(page, path));
  test("unknown conversation shows a not-found state, not a crash", async ({ page }) => {
    const problems = watch(page);
    await page.goto("/c/00000000-0000-4000-8000-000000000000");
    await expect(page.getByRole("heading", { name: "This chat doesn't exist" })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Message Nova" })).toHaveCount(0); // nothing to send into
    await page.getByRole("link", { name: "Start a new chat" }).click();
    await expect(page).toHaveURL(/\/chat$/);
    expect(problems.filter((p) => !p.includes("404"))).toEqual([]);
  });
  test("admin pages are closed to non-admins without crashing", async ({ page }) => {
    for (const path of ADMIN) {
      const problems = watch(page);
      const res = await page.goto(path);
      expect(res?.status(), path).toBeLessThan(500);
      await page.waitForLoadState("networkidle");
      // The admin area isn't revealed: non-admins get the regular "doesn't exist" page.
      await expect(page.getByRole("heading", { name: "This page doesn't exist" }), path).toBeVisible();
      expect(problems.filter((p) => !/403|404/.test(p)), path).toEqual([]);
    }
  });
});

import { expect, test } from "@playwright/test";

test("Mac app download page", async ({ page, request }) => {
  await page.goto("/download");
  await expect(page.getByRole("heading", { name: "Nova for Mac" })).toBeVisible();
  const button = page.getByRole("link", { name: /Download for Mac/ });
  if (await button.count()) {
    // Published (make desktop-release): the stable link redirects to the installer.
    const r = await request.get("/download/mac", { maxRedirects: 0 });
    expect(r.status()).toBe(307);
    expect(r.headers()["location"]).toMatch(/Nova-mac\.dmg$/);
    const bad = await request.get("/download/amiga", { maxRedirects: 0 });
    expect(bad.headers()["location"]).toMatch(/\/download$/);
  } else {
    await expect(page.getByText(/hasn't been published on this server yet/)).toBeVisible();
  }
});

import { execFileSync } from "node:child_process";
import fs from "node:fs";

import { test as setup } from "@playwright/test";

import { signUp } from "./helpers";

export const STATE = "playwright/.auth/user.json";

// One account per run: signups are rate limited per IP (5/hour, docs/34). Local reruns reuse
// the saved session while it's still valid.
setup("sign up", async ({ browser, baseURL }) => {
  if (!process.env.CI && fs.existsSync(STATE)) {
    const ctx = await browser.newContext({ storageState: STATE });
    const res = await ctx.request.get(`${baseURL}/api/v1/users/me`);
    await ctx.close();
    if (res.ok()) return;
  }
  const page = await browser.newPage();
  const email = await signUp(page);
  // Free plan allows 6 chat messages/min; the shared account sends more than that.
  execFileSync("uv", ["run", "python", "-m", "tests.fakes.e2e_promote", email], { cwd: "../api", stdio: "inherit" });
  await page.context().storageState({ path: STATE });
  await page.close();
});

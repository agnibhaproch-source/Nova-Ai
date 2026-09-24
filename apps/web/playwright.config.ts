import { defineConfig, devices } from "@playwright/test";

/**
 * E2E against the real stack with the Groq stub (docs/40 §6). Starts the stub, API and web
 * unless they're already running (CI starts from scratch). Never points at real Groq.
 */
const API_DIR = "../api";
const STATE = "playwright/.auth/user.json";
const CI = !!process.env.CI;

// Isolated ports so E2E never touches the dev stack (web 3000 / API 8000 on real Groq).
const WEB = 3100;
const API = 8010;
const STUB = 8099;

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 60_000,
  retries: CI ? 1 : 0,
  workers: 1,
  reporter: CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: { baseURL: `http://localhost:${WEB}`, trace: "retain-on-failure" },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    { name: "desktop-chrome", dependencies: ["setup"], use: { ...devices["Desktop Chrome"], storageState: STATE } },
    { name: "mobile-chrome", dependencies: ["setup"], use: { ...devices["Pixel 7"], storageState: STATE } },
  ],
  webServer: [
    {
      command: `uv run uvicorn tests.fakes.groq_stub_server:app --port ${STUB}`,
      cwd: API_DIR,
      url: `http://localhost:${STUB}/openai/v1/models`,
      reuseExistingServer: !CI,
    },
    {
      // The worker processes uploads (screenshots → ready); it dies with this shell.
      command: `sh -c "uv run arq app.workers.settings.WorkerSettings & exec uv run uvicorn app.main:app --port ${API}"`,
      cwd: API_DIR,
      url: `http://localhost:${API}/healthz`,
      env: { GROQ_BASE_URL: `http://localhost:${STUB}`, GROQ_KEY_MODE: "user", APP_URL: `http://localhost:${WEB}` },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: CI ? `pnpm build && pnpm start -p ${WEB}` : `pnpm dev -p ${WEB}`,
      url: `http://localhost:${WEB}/login`,
      env: { NEXT_DIST_DIR: ".next-e2e", API_INTERNAL_URL: `http://localhost:${API}`, APP_URL: `http://localhost:${WEB}` },
      reuseExistingServer: false,
      timeout: 240_000,
    },
  ],
});

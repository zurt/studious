import { defineConfig, devices } from "@playwright/test";

// Dedicated ports so E2E runs never collide with (or reuse) a real dev
// stack on 8000/5173 — the backend here uses the mock VLM provider and an
// isolated data dir, and must stay that way. Not 8765: that is AnkiConnect's
// port, so the suite could not start while Anki was open.
const BACKEND_PORT = 8775;
const FRONTEND_PORT = 5273;

export default defineConfig({
  testDir: "./e2e",
  // Journeys share one backend data dir and build on each other's state
  // (upload → chapter → …), so they must run in order on a single worker.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://localhost:${FRONTEND_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // Fresh data dir every run; STUDIOUS_VLM_PROVIDER=mock registers the
      // canned mock VLM under the "anthropic" name at app startup.
      command: `rm -rf .e2e-data && uv run uvicorn app.main:app --port ${BACKEND_PORT}`,
      cwd: "../backend",
      url: `http://localhost:${BACKEND_PORT}/api/health`,
      reuseExistingServer: false,
      env: {
        STUDIOUS_DATA_DIR: ".e2e-data",
        STUDIOUS_VLM_PROVIDER: "mock",
        // Never reach a real Anthropic key, WaniKani or Anki from the suite.
        ANTHROPIC_API_KEY: "",
        WANIKANI_API_TOKEN: "",
        // No background card audio: the suite may run on a Mac where `say` exists.
        STUDIOUS_TTS_PREGENERATE: "0",
        STUDIOUS_PDF_RENDER_DPI: "100",
        STUDIOUS_LOG_LEVEL: "WARNING",
      },
      timeout: 30_000,
    },
    {
      command: `npm run dev -- --port ${FRONTEND_PORT} --strictPort`,
      url: `http://localhost:${FRONTEND_PORT}`,
      reuseExistingServer: false,
      env: { STUDIOUS_BACKEND_PORT: String(BACKEND_PORT) },
      timeout: 30_000,
    },
  ],
});

import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testIgnore: ["robrix-*.spec.mjs"],
  testDir: "./e2e",
  fullyParallel: false,
  // The fixture owns one ledger. Projects/files must not reset it concurrently.
  workers: 1,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: [["line"], ["json", { outputFile: "test-results/browser-results.json" }], ["html", { open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
  webServer: {
    command: "node test/fixtures/server.mjs",
    port: 4173,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});

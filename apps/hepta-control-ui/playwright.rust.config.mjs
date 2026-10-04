import base from "./playwright.config.mjs";
import { defineConfig } from "@playwright/test";
export default defineConfig({
  ...base,
  projects: base.projects.map(project => project.name === "chromium" && process.env.UI_CONTROL_CHROMIUM_EXECUTABLE
    ? { ...project, use: { ...project.use, launchOptions: { executablePath: process.env.UI_CONTROL_CHROMIUM_EXECUTABLE } } }
    : project),
  reporter: [["line"], ["json", { outputFile: "test-results/rust-browser-results.json" }]],
  use: { ...base.use, baseURL: "http://127.0.0.1:4174" },
  webServer: { ...base.webServer, port: 4174, reuseExistingServer: false,
    env: { UI_CONTROL_CANDIDATE: "rust", PORT: "4174" } },
});

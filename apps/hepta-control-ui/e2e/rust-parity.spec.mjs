import { expect, test } from "@playwright/test";
import { loadControlConsole } from "./readiness.mjs";

// These scenarios apply to both implementations. Rust runs are selected by the
// independent candidate profile, never by replacing the live JavaScript path.
test.beforeEach(async ({ request }) => { await request.get("/__test__/reset"); });

async function submit(page, reason = "Preserve exact recovery identity.") {
  await page.getByLabel("Reason").fill(reason);
  await page.getByRole("button", { name: "Request reconcile", exact: true }).click();
  await page.getByRole("button", { name: "Submit request", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
}

async function recoveryKeys(page) {
  return page.evaluate(() => Object.keys(localStorage).filter(key => key.startsWith("hepta.ui-control.scoped-recovery.v2:")));
}

test("a malformed rejection cannot retire its unresolved durable identity", async ({ page, request }) => {
  await loadControlConsole(page);
  await page.route("**/api/ui-control/v1/operations", route => route.fulfill({
    status: 200, json: { accepted: false, constructor: "untrusted-field" },
  }));
  await submit(page);
  await expect(page.locator("#error-status")).toContainText("UI_CONTROL_AMBIGUOUS_SUBMISSION");
  await expect(page.locator("#pending-list")).toContainText("indeterminate");
  expect(await recoveryKeys(page)).toHaveLength(1);
  expect((await (await request.get("/__test__/state")).json()).requestCount).toBe(0);
});

test("unavailable Web Locks disables mutations and keeps diagnostics usable", async ({ page, request }) => {
  await page.addInitScript(() => Object.defineProperty(Navigator.prototype, "locks", { configurable: true, get: () => undefined }));
  await page.goto("/");
  await expect(page.getByRole("cell", { name: "runtime.agentd", exact: true })).toBeVisible();
  await expect(page.locator("#error-status")).toContainText("UI_CONTROL_STORAGE");
  await expect(page.getByRole("button", { name: "Request start", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Refresh runtime view", exact: true })).toBeEnabled();
  expect((await (await request.get("/__test__/state")).json()).requestCount).toBe(0);
});

test("short-lived session refresh cannot starve runtime polling", async ({ page }) => {
  let snapshots = 0;
  let refreshes = 0;
  for (const routePath of ["session/connect", "session/refresh"]) {
    await page.route(`**/api/ui-control/v1/${routePath}`, async route => {
      const response = await route.fetch();
      const body = await response.json();
      if (routePath === "session/refresh") refreshes += 1;
      await route.fulfill({ response, json: { ...body, expiresAt: Date.now() + 30_000 } });
    });
  }
  await page.route("**/api/ui-control/v1/view", async route => { snapshots += 1; await route.continue(); });
  await loadControlConsole(page);
  await expect.poll(() => refreshes, { timeout: 8000 }).toBeGreaterThanOrEqual(2);
  await expect.poll(() => snapshots, { timeout: 8000 }).toBeGreaterThanOrEqual(3);
});

test("fatal startup recovery cannot announce an authenticated ready console", async ({ page }) => {
  await loadControlConsole(page);
  await submit(page);
  expect(await recoveryKeys(page)).toHaveLength(1);
  await page.route("**/api/ui-control/v1/operations/*", route => route.fulfill({ status: 401, json: { errorCode: "SESSION_EXPIRED" } }));
  await page.reload();
  await expect.poll(() => page.evaluate(() => globalThis.__heptaUiControlReadiness?.phase)).toBe("failed");
  await expect(page.locator("#connection-state")).toHaveText("Disconnected");
  await expect(page.getByRole("button", { name: "Request start", exact: true })).toBeDisabled();
  expect(await recoveryKeys(page)).toHaveLength(1);
});

test("two tabs agree that an already-cleaned terminal record is settled", async ({ page, context, request }) => {
  await loadControlConsole(page); await submit(page);
  const second = await context.newPage(); await loadControlConsole(second);
  const operation = (await (await request.get("/__test__/state")).json()).operations[0];
  await request.get(`/__test__/complete?operationId=${encodeURIComponent(operation.operationId)}`);
  await page.getByRole("button", { name: "Refresh runtime view", exact: true }).click();
  await expect(page.locator("#completed-list")).toContainText("succeeded");
  await second.getByRole("button", { name: "Refresh runtime view", exact: true }).click();
  await expect(second.locator("#completed-list")).toContainText("succeeded");
  await expect.poll(() => recoveryKeys(second)).toEqual([]);
  await expect(second.locator("#error-status")).toBeHidden();
  expect((await (await request.get("/__test__/state")).json()).requestCount).toBe(1);
  await second.close();
});

test("narrow console keeps controls, confirmation and error diagnostics readable", async ({ page, request }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await loadControlConsole(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("narrow-console.png"), fullPage: true });
  await page.getByLabel("Reason").fill("Review the narrow-window confirmation.");
  await page.getByRole("button", { name: "Request reconcile", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("narrow-confirmation.png"), fullPage: true });
  await request.get("/__test__/bump");
  await page.getByRole("button", { name: "Submit request", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(page.locator("#error-status")).toContainText("UI_CONTROL_STALE_REVISION");
  await page.screenshot({ path: testInfo.outputPath("narrow-error.png"), fullPage: true });
});

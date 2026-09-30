import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { loadControlConsole } from "./readiness.mjs";

function redactedIdentifier(value) {
  const input = String(value);
  if (input.length <= 4) return "••••";
  if (input.length <= 12) return `${input.slice(0, 4)}…${input.slice(-2)}`;
  return `${input.slice(0, 8)}…${input.slice(-6)}`;
}

async function reset(request) {
  const response = await request.get("/__test__/reset");
  expect(response.ok()).toBeTruthy();
}

async function loadConsole(page) {
  const receipt = await loadControlConsole(page);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "runtime.agentd" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Request start" })).toBeEnabled();
  return receipt;
}

test.beforeEach(async ({ request }) => { await reset(request); });

test("browser shell exposes a coherent accessible control view with redacted session material", async ({ page }) => {
  await loadConsole(page);
  await expect(page.getByText("sess…-1", { exact: true })).toBeVisible();
  await expect(page.getByText("session-1", { exact: true })).toHaveCount(0);
  await expect(page.getByText("operator-1", { exact: true })).toBeVisible();
  await expect(page.getByText("11", { exact: true }).first()).toBeVisible();
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test("keyboard confirmation traps intent, defaults to cancel, redacts identifiers, and restores focus", async ({ page }) => {
  await loadConsole(page);
  await page.getByLabel("Reason").fill("Operator-confirmed maintenance stop.");
  const stop = page.getByRole("button", { name: "Request stop" });
  await stop.focus(); await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.locator("#confirm-summary")).toContainText(/Snapshot digest: [0-9a-f]{12}…[0-9a-f]{8}/);
  await expect(page.locator("#confirm-summary")).toContainText(/Operation ID: ui:[0-9a-f]{5}…[0-9a-f-]{6}/);
  await expect(page.locator("#confirm-summary")).not.toContainText(/[0-9a-f]{64}/);
  await expect(page.locator("#confirm-cancel")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden(); await expect(stop).toBeFocused();
});

test("double activation produces one server operation and renders redacted audit identity", async ({ page, request }) => {
  await loadConsole(page);
  await page.getByLabel("Reason").fill("Start after validated dependency recovery.");
  await page.getByRole("button", { name: "Request start" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.evaluate(() => {
    const button = document.getElementById("confirm-submit"); button.click(); button.click();
  });
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(page.locator("#pending-list")).toContainText(/audit-ui…[0-9a-f-]{6}/);
  await expect(page.locator("#pending-list")).toContainText(/digest [0-9a-f]{12}…[0-9a-f]{8}/);
  const state = await (await request.get("/__test__/state")).json();
  expect(state.requestCount).toBe(1); expect(state.operations).toHaveLength(1);
  await expect(page.locator("body")).not.toContainText(state.operations[0].operationId);
  await expect(page.locator("body")).not.toContainText(state.operations[0].semanticDigest);
  await expect(page.locator("body")).not.toContainText(state.operations[0].auditTraceId);
});

test("server-side stale revision rejection is typed and does not create an operation", async ({ page, request }) => {
  await loadConsole(page);
  await page.getByLabel("Reason").fill("Stop using the displayed revision.");
  await page.getByRole("button", { name: "Request stop" }).click();
  await request.get("/__test__/bump");
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByRole("alert")).toContainText("UI_CONTROL_STALE_REVISION");
  const state = await (await request.get("/__test__/state")).json(); expect(state.requestCount).toBe(0);
});

test("accepted-but-disconnected operation remains recoverable by operation id", async ({ page, request }) => {
  // Keep automatic lookup missing until the explicit recovery request.
  let permitLookup = false;
  await page.route("**/api/ui-control/v1/operations/*", async route => {
    if (!permitLookup) await route.fulfill({ status: 200, json: { found: false } });
    else await route.continue();
  });
  await loadConsole(page);
  await page.getByLabel("Reason").fill("AMBIGUOUS response-loss qualification.");
  await page.getByRole("button", { name: "Request reconcile" }).click();
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByRole("alert")).toContainText("UI_CONTROL_AMBIGUOUS_SUBMISSION");
  await expect(page.getByRole("button", { name: /Recover operation/ })).toBeVisible();
  permitLookup = true;
  await page.getByRole("button", { name: /Recover operation/ }).click();
  await expect(page.locator("#pending-list")).toContainText("pending");
  const state = await (await request.get("/__test__/state")).json(); expect(state.requestCount).toBe(1);
});

test("authenticated terminal observation moves an operation into redacted terminal evidence", async ({ page, request }) => {
  await loadConsole(page);
  await page.getByLabel("Reason").fill("Reconcile and observe a terminal backend fact.");
  await page.getByRole("button", { name: "Request reconcile" }).click();
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  const before = await (await request.get("/__test__/state")).json();
  const operationId = before.operations[0].operationId;
  const completion = await request.get(`/__test__/complete?operationId=${encodeURIComponent(operationId)}`);
  expect(completion.ok()).toBeTruthy();
  await page.getByRole("button", { name: "Refresh runtime view" }).click();
  await expect(page.locator("#completed-list")).toContainText(redactedIdentifier(operationId));
  await expect(page.locator("#completed-list")).not.toContainText(operationId);
  await expect(page.locator("#completed-list")).toContainText("succeeded");
  await expect(page.locator("#pending-list")).toContainText("No pending operations.");
});

test("unexpected storage errors remain private and preserve read-only diagnostics", async ({ page }) => {
  await page.addInitScript(() => {
    Storage.prototype.getItem = function sensitiveStorageFailure() { throw new Error("session-cookie=must-not-appear"); };
  });
  await page.goto("/", { waitUntil: "commit" });
  await expect(page.getByRole("cell", { name: "runtime.agentd" })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("UI_CONTROL_STORAGE");
  await expect(page.getByRole("alert")).not.toContainText("session-cookie=must-not-appear");
  await expect(page.getByRole("button", { name: "Request start" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Refresh runtime view" })).toBeEnabled();
});

test("local recovery storage denial prevents dispatch without wedging read-only diagnostics", async ({ page, request }) => {
  await loadConsole(page);
  await page.evaluate(() => {
    Storage.prototype.setItem = function deniedStorageWrite() { throw new DOMException("storage denied", "SecurityError"); };
  });
  await page.getByLabel("Reason").fill("Do not dispatch when recovery cannot be persisted.");
  await page.getByRole("button", { name: "Request start" }).click();
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(page.getByRole("alert")).toContainText("UI_CONTROL_STORAGE");
  await expect(page.getByRole("button", { name: "Refresh runtime view" })).toBeEnabled();
  const state = await (await request.get("/__test__/state")).json(); expect(state.requestCount).toBe(0);
});

test("lost runtime refresh marks the product stale and disables controls until recovery", async ({ page, request }) => {
  await loadConsole(page);
  await page.route("**/api/ui-control/v1/view", route => route.abort("connectionfailed"));
  await page.getByRole("button", { name: "Refresh runtime view" }).click();
  await expect(page.locator("#stale-banner")).toBeVisible();
  for (const name of ["Request start", "Request reconcile", "Request stop"]) {
    await expect(page.getByRole("button", { name })).toBeDisabled();
  }
  await expect(page.getByRole("alert")).toContainText("UI_CONTROL_TRANSPORT");
  expect((await (await request.get("/__test__/state")).json()).requestCount).toBe(0);
  await page.unroute("**/api/ui-control/v1/view");
  await page.getByRole("button", { name: "Refresh runtime view" }).click();
  await expect(page.locator("#stale-banner")).toBeHidden();
  await expect(page.getByRole("button", { name: "Request start" })).toBeEnabled();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

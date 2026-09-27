import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

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
  await page.goto("/");
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "runtime.agentd" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Request start" })).toBeEnabled();
}

test.beforeEach(async ({ request }) => {
  await reset(request);
});

test("browser shell exposes a coherent accessible control view with redacted session material", async ({ page }) => {
  await loadConsole(page);
  await expect(page.getByText("sess…-1", { exact: true })).toBeVisible();
  await expect(page.getByText("session-1", { exact: true })).toHaveCount(0);
  await expect(page.getByText("operator-1", { exact: true })).toBeVisible();
  await expect(page.getByText("11", { exact: true }).first()).toBeVisible();
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test("keyboard confirmation traps intent, redacts identifiers, and restores focus on cancel", async ({ page }) => {
  await loadConsole(page);
  await page.getByLabel("Reason").fill("Operator-confirmed maintenance stop.");
  const stop = page.getByRole("button", { name: "Request stop" });
  await stop.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.locator("#confirm-summary")).toContainText(/Snapshot digest: [0-9a-f]{12}…[0-9a-f]{8}/);
  await expect(page.locator("#confirm-summary")).toContainText(/Operation ID: ui:[0-9a-f]{5}…[0-9a-f-]{6}/);
  await expect(page.locator("#confirm-summary")).not.toContainText(/[0-9a-f]{64}/);
  await expect(page.getByRole("button", { name: "Submit request" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(stop).toBeFocused();
});

test("double activation produces one server operation and renders redacted audit identity", async ({ page, request }) => {
  await loadConsole(page);
  await page.getByLabel("Reason").fill("Start after validated dependency recovery.");
  await page.getByRole("button", { name: "Request start" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.evaluate(() => {
    const button = document.getElementById("confirm-submit");
    button.click();
    button.click();
  });
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(page.getByText(/audit-ui…[0-9a-f-]{6}/)).toBeVisible();
  await expect(page.getByText(/digest [0-9a-f]{12}…[0-9a-f]{8}/)).toBeVisible();
  const state = await (await request.get("/__test__/state")).json();
  expect(state.requestCount).toBe(1);
  expect(state.operations).toHaveLength(1);
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
  const state = await (await request.get("/__test__/state")).json();
  expect(state.requestCount).toBe(0);
});

test("accepted-but-disconnected operation remains recoverable by operation id", async ({ page, request }) => {
  await loadConsole(page);
  await page.getByLabel("Reason").fill("AMBIGUOUS response-loss qualification.");
  await page.getByRole("button", { name: "Request reconcile" }).click();
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByRole("alert")).toContainText("UI_CONTROL_AMBIGUOUS_SUBMISSION");
  await expect(page.getByRole("button", { name: /Recover operation/ })).toBeVisible();
  await page.getByRole("button", { name: /Recover operation/ }).click();
  await expect(page.getByText(/pending/)).toBeVisible();
  const state = await (await request.get("/__test__/state")).json();
  expect(state.requestCount).toBe(1);
});

test("authenticated terminal observation moves an operation into redacted terminal evidence", async ({ page, request }) => {
  await loadConsole(page);
  await page.getByLabel("Reason").fill("Reconcile and observe a terminal backend fact.");
  await page.getByRole("button", { name: "Request reconcile" }).click();
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();

  const before = await (await request.get("/__test__/state")).json();
  const operationId = before.operations[0].operationId;
  const completion = await request.get(
    `/__test__/complete?operationId=${encodeURIComponent(operationId)}`,
  );
  expect(completion.ok()).toBeTruthy();

  await page.getByRole("button", { name: "Refresh runtime view" }).click();
  await expect(page.locator("#completed-list")).toContainText(redactedIdentifier(operationId));
  await expect(page.locator("#completed-list")).not.toContainText(operationId);
  await expect(page.locator("#completed-list")).toContainText("succeeded");
  await expect(page.locator("#pending-list")).toContainText("No pending operations.");
});

test("unexpected errors do not reflect raw messages into the operator DOM", async ({ page }) => {
  await page.addInitScript(() => {
    Storage.prototype.getItem = function sensitiveStorageFailure() {
      throw new Error("session-cookie=must-not-appear");
    };
  });
  await loadConsole(page);
  await expect(page.getByRole("alert")).not.toContainText("session-cookie=must-not-appear");
});

test("local recovery storage denial cannot wedge a submitted control request", async ({ page, request }) => {
  await page.addInitScript(() => {
    Storage.prototype.setItem = function deniedStorageWrite() {
      throw new DOMException("storage denied", "SecurityError");
    };
  });
  await loadConsole(page);
  await page.getByLabel("Reason").fill("Submit while local recovery storage is unavailable.");
  await page.getByRole("button", { name: "Request start" }).click();
  await page.getByRole("button", { name: "Submit request" }).click();

  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(page.getByRole("alert")).toContainText("UI_CONTROL_STORAGE");
  await expect(page.getByRole("button", { name: "Refresh runtime view" })).toBeEnabled();
  const state = await (await request.get("/__test__/state")).json();
  expect(state.requestCount).toBe(1);
});

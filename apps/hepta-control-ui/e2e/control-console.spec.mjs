import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

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

test("browser shell exposes a coherent accessible control view", async ({ page }) => {
  await loadConsole(page);
  await expect(page.getByText("session-1", { exact: true })).toBeVisible();
  await expect(page.getByText("operator-1", { exact: true })).toBeVisible();
  await expect(page.getByText("11", { exact: true }).first()).toBeVisible();
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test("keyboard confirmation traps intent and restores focus on cancel", async ({ page }) => {
  await loadConsole(page);
  await page.getByLabel("Reason").fill("Operator-confirmed maintenance stop.");
  const stop = page.getByRole("button", { name: "Request stop" });
  await stop.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("button", { name: "Submit request" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(stop).toBeFocused();
});

test("double activation produces one server operation and renders audit identity", async ({ page, request }) => {
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
  await expect(page.getByText(/audit-ui:/)).toBeVisible();
  await expect(page.getByText(/digest [0-9a-f]{64}/)).toBeVisible();
  const state = await (await request.get("/__test__/state")).json();
  expect(state.requestCount).toBe(1);
  expect(state.operations).toHaveLength(1);
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
  await expect(page.getByRole("button", { name: "Recover operation" })).toBeVisible();
  await page.getByRole("button", { name: "Recover operation" }).click();
  await expect(page.getByText(/pending/)).toBeVisible();
  const state = await (await request.get("/__test__/state")).json();
  expect(state.requestCount).toBe(1);
});

test("authenticated terminal observation moves an operation into terminal evidence", async ({ page, request }) => {
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
  await expect(page.locator("#completed-list")).toContainText(operationId);
  await expect(page.locator("#completed-list")).toContainText("succeeded");
  await expect(page.locator("#pending-list")).toContainText("No pending operations.");
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

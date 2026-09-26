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
  const state = await (await request.get("/__test__/state")).json();
  expect(state.requestCount).toBe(1);
  expect(state.operations).toHaveLength(1);
});

test("server-side stale revision rejection is visible and does not create an operation", async ({ page, request }) => {
  await loadConsole(page);
  await page.getByLabel("Reason").fill("Stop using the displayed revision.");
  await page.getByRole("button", { name: "Request stop" }).click();
  await request.get("/__test__/bump");
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByRole("alert")).toContainText("UI_CONTROL_BACKEND_REJECTED");
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

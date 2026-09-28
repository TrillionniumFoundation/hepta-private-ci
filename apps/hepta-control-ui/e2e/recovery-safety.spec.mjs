import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { loadControlConsole } from "./readiness.mjs";

async function load(page) {
  const receipt = await loadControlConsole(page);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Request start", exact: true })).toBeEnabled();
  return receipt;
}
async function records(page) {
  return page.evaluate(() => Object.keys(localStorage)
    .filter(key => key.startsWith("hepta.ui-control.scoped-recovery.v2:"))
    .map(key => JSON.parse(localStorage.getItem(key)).operation));
}
async function submit(page, reason) {
  await page.getByLabel("Reason", { exact: true }).fill(reason);
  await page.getByRole("button", { name: "Request start", exact: true }).click();
  await page.getByRole("button", { name: "Submit request", exact: true }).click();
}

test.beforeEach(async ({ request }) => {
  expect((await request.get("/__test__/reset")).ok()).toBeTruthy();
});

test("same revision in a new generation invalidates an open confirmation", async ({ page, request }) => {
  let roll = false;
  await page.route("**/api/ui-control/v1/view", async route => {
    const response = await route.fetch(); const data = await response.json();
    if (roll) data.generation += 1;
    await route.fulfill({ response, json: data });
  });
  await load(page);
  await page.getByLabel("Reason", { exact: true }).fill("Confirm the original generation only.");
  await page.getByRole("button", { name: "Request stop", exact: true }).click();
  await expect(page.locator("#confirm-cancel")).toBeFocused();
  roll = true;
  await expect(page.locator("#generation-state")).toHaveText("8");
  await page.getByRole("button", { name: "Submit request", exact: true }).click();
  await expect(page.locator("#error-status")).toContainText("UI_CONTROL_STALE_REVISION");
  expect((await (await request.get("/__test__/state")).json()).requestCount).toBe(0);
});

test("polling preserves target and reason focus; target removal requires a new selection", async ({ page }) => {
  let revision = 11; let remove = false;
  await page.route("**/api/ui-control/v1/view", async route => {
    const response = await route.fetch(); const data = await response.json();
    data.revision = revision;
    if (remove) data.modules = data.modules.filter(module => module.id !== "runtime.fleet");
    await route.fulfill({ response, json: data });
  });
  await load(page);
  await page.locator("#target-id").selectOption("runtime.fleet");
  await page.getByLabel("Reason", { exact: true }).fill("Keep this selected target.");
  await page.getByLabel("Reason", { exact: true }).focus();
  revision = 12;
  await expect(page.locator("#revision-state")).toHaveText("12");
  await expect(page.locator("#target-id")).toHaveValue("runtime.fleet");
  await expect(page.getByLabel("Reason", { exact: true })).toBeFocused();
  remove = true; revision = 13;
  await expect(page.locator("#revision-state")).toHaveText("13");
  await expect(page.locator("#target-id")).toHaveValue("");
  await expect(page.getByRole("button", { name: "Request stop", exact: true })).toBeDisabled();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test("response held after server admission survives page loss without a replacement operation", async ({ page, context, request, browserName }) => {
  await load(page);
  await submit(page, "HOLD_RESPONSE after durable admission while the original page is lost.");
  await expect.poll(async () => (await (await request.get("/__test__/state")).json()).requestCount).toBe(1);
  await expect.poll(async () => (await (await request.get("/__test__/state")).json()).heldResponseCount).toBe(1);
  const prepared = await records(page);
  expect(prepared).toHaveLength(1);
  expect(prepared[0].state).toBe("submitting");
  await expect(page.getByRole("dialog")).toBeVisible();
  try {
    if (browserName === "chromium") {
      const session = await context.newCDPSession(page);
      const crashed = page.waitForEvent("crash");
      void session.send("Page.crash").catch(() => {});
      await crashed;
    } else {
      // Other engines cover abrupt document/page loss; the response is still
      // held by the server fixture, not by a Playwright route handler.
      await page.close({ runBeforeUnload: false });
    }

    // Release the fixture response only after the original document is gone.
    // The acknowledgement can no longer reach that document; the replacement
    // must recover the already-admitted operation from the durable identity.
    expect((await request.get("/__test__/release-held")).ok()).toBeTruthy();
    await expect.poll(async () =>
      (await (await request.get("/__test__/state")).json()).heldResponseCount,
    ).toBe(0);

    const replacement = await context.newPage();
    await load(replacement);
    await expect(replacement.locator("#pending-list")).toContainText("pending");
    expect((await records(replacement))[0].operationId).toBe(prepared[0].operationId);
    expect((await (await request.get("/__test__/state")).json()).requestCount).toBe(1);
    await replacement.close();
  } finally {
    await request.get("/__test__/release-held");
  }
});

test("two tabs keep tab-private sessions while sharing scoped recovery records", async ({ page, context, request }) => {
  const firstReadiness = await load(page);
  const other = await context.newPage();
  const secondReadiness = await load(other);

  expect(secondReadiness.tabId).not.toBe(firstReadiness.tabId);
  expect(firstReadiness.stateOwnership.activeSession).toBe("tab-private");
  expect(secondReadiness.stateOwnership.activeSession).toBe("tab-private");
  expect(firstReadiness.stateOwnership.recoveryRecords)
    .toBe("endpoint-protocol-identity-scoped-cross-tab");

  await Promise.all([submit(page, "First tab operation."), submit(other, "Second tab operation.")]);
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(other.getByRole("dialog")).toBeHidden();
  const state = await (await request.get("/__test__/state")).json();
  expect(state.requestCount).toBe(2);
  expect((await records(page)).map(operation => operation.operationId).sort())
    .toEqual(state.operations.map(operation => operation.operationId).sort());
  await other.close();
});

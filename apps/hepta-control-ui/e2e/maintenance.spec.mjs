import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { loadControlConsole } from "./readiness.mjs";

async function load(page) {
  await loadControlConsole(page);
  await expect(page.getByRole("button", { name: "Request start", exact: true })).toBeEnabled();
}
async function refresh(page) {
  const button = page.getByRole("button", { name: "Refresh runtime view", exact: true });
  await button.click(); await expect(button).toBeEnabled({ timeout: 10000 });
}
async function records(page) {
  return page.evaluate(() => Object.keys(localStorage)
    .filter(key => key.startsWith("hepta.ui-control.scoped-recovery.v2:")));
}

test.beforeEach(async ({ request }) => {
  expect((await request.get("/__test__/reset")).ok()).toBeTruthy();
});

test("large product table reuses nodes across refresh and preserves reason focus", async ({ page }) => {
  await load(page);

  // Capture one authenticated product response before interception. The stress
  // fixture is then completely local and cannot retain a route.fetch response
  // across Firefox navigation or test teardown.
  const seedResponse = await page.context().request.get("/api/ui-control/v1/view");
  expect(seedResponse.ok()).toBeTruthy();
  const seed = await seedResponse.json();
  await seedResponse.dispose();
  expect(seed.modules.length).toBeGreaterThan(0);

  const base = seed.modules[0];
  const largeModules = Array.from({ length: 512 }, (_, i) => ({
    ...base,
    id: `runtime.scale${i}`,
  }));
  let change = false;
  let interceptedViews = 0;
  const viewRoute = "**/api/ui-control/v1/view";
  await page.route(viewRoute, async route => {
    interceptedViews += 1;
    const modules = largeModules.map(module => ({ ...module }));
    if (change) modules[100].revision += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...seed,
        revision: seed.revision + (change ? 1 : 0),
        modules,
      }),
    });
  });
  await refresh(page);
  await expect(page.locator("#modules-body").locator(":scope > *")).toHaveCount(512);

  const observation = await page.evaluateHandle(() => {
    const containers = ["modules-body", "pending-list", "completed-list"].map(id => document.getElementById(id));
    const state = { rows: [...containers[0].children], mutations: 0 };
    state.observer = new MutationObserver(changes => { state.mutations += changes.length; });
    containers.forEach(element => state.observer.observe(element, { childList: true, subtree: true, characterData: true }));
    return state;
  });
  const viewsBeforeSteadyRefresh = interceptedViews;
  for (let i = 0; i < 5; i += 1) await refresh(page);
  expect(interceptedViews).toBeGreaterThanOrEqual(viewsBeforeSteadyRefresh + 5);
  expect(await observation.evaluate(state => state.mutations)).toBe(0);
  await page.getByLabel("Reason", { exact: true }).fill("Keep keyboard focus on the reason.");
  await page.getByLabel("Reason", { exact: true }).focus();
  change = true;
  // Let the ordinary product poller observe the revision; do not call a test-only renderer.
  await expect(page.locator("#revision-state")).toHaveText(String(seed.revision + 1));
  await expect(page.getByLabel("Reason", { exact: true })).toBeFocused();
  expect(await observation.evaluate(state => state.rows.every((row, i) => row === document.getElementById("modules-body").children[i]))).toBe(true);
  await observation.evaluate(state => state.observer.disconnect());
  await observation.dispose();
  await page.unroute(viewRoute);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

for (const fault of ["delete-readback", "lock-deadline"]) {
  test(`terminal ${fault} failure remains visible and never causes mutation replay`, async ({ page, request }) => {
    await load(page);
    await page.getByLabel("Reason", { exact: true }).fill("Observe terminal cleanup without replay.");
    await page.getByRole("button", { name: "Request start", exact: true }).click();
    await page.getByRole("button", { name: "Submit request", exact: true }).click();
    await expect(page.getByRole("dialog")).toBeHidden();
    const before = await (await request.get("/__test__/state")).json();
    const id = before.operations[0].operationId;
    const [key] = await records(page);
    expect(key).toBeTruthy();
    if (fault === "delete-readback") {
      await page.evaluate(() => {
        const original = Storage.prototype.removeItem;
        Storage.prototype.removeItem = function (key) {
          if (!key.startsWith("hepta.ui-control.scoped-recovery.v2:")) return original.call(this, key);
        };
        globalThis.releaseMaintenanceFault = () => { Storage.prototype.removeItem = original; };
      });
    } else {
      const prefix = key.slice(0, -(id.length));
      await page.evaluate(prefix => new Promise(resolve => {
        void navigator.locks.request(prefix, { mode: "exclusive" }, () => new Promise(release => {
          globalThis.releaseMaintenanceFault = release; resolve();
        }));
      }), prefix);
    }
    expect((await request.get(`/__test__/complete?operationId=${encodeURIComponent(id)}`)).ok()).toBeTruthy();
    await refresh(page);
    await expect(page.locator("#completed-list")).toContainText("succeeded");
    await expect(page.locator("#error-status")).toContainText("UI_CONTROL_STORAGE");
    expect(await records(page)).toEqual([key]);
    await page.evaluate(() => globalThis.releaseMaintenanceFault());
    await refresh(page);
    await expect.poll(() => records(page)).toEqual([]);
    await expect(page.locator("#error-status")).toBeHidden();
    const after = await (await request.get("/__test__/state")).json();
    expect(after.requestCount).toBe(1);
    expect(after.operations[0].operationId).toBe(id);
  });
}

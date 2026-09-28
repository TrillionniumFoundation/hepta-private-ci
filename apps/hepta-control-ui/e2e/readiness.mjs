import { expect } from "@playwright/test";

const READINESS_SCHEMA = "hepta.ui-control.readiness.v1";

export async function loadControlConsole(page) {
  const response = await page.goto("/", { waitUntil: "commit" });
  expect(response, "navigation must produce an HTTP response").not.toBeNull();
  expect(response.ok(), `navigation failed with HTTP ${response.status()}`).toBeTruthy();

  await page.waitForFunction(
    () => {
      const marker = document.documentElement.dataset.uiControlReady;
      const phase = globalThis.__heptaUiControlReadiness?.phase;
      return marker === "true" || marker === "failed" || phase === "failed";
    },
    undefined,
    { timeout: 30_000 },
  );

  const receipt = await page.evaluate(() =>
    JSON.parse(JSON.stringify(globalThis.__heptaUiControlReadiness ?? null)),
  );
  expect(receipt, "the browser application must publish a readiness receipt").not.toBeNull();
  expect(receipt.schema).toBe(READINESS_SCHEMA);
  expect(receipt.phase, `startup failed with ${receipt.errorCode ?? "unknown error"}`).toBe("ready");
  expect(receipt.tabId).toMatch(/^tab:/);
  expect(receipt.stateOwnership).toEqual({
    activeSession: "tab-private",
    selectionAndFocus: "tab-private",
    recoveryRecords: "endpoint-protocol-identity-scoped-cross-tab",
    leaderAndClaims: "scope-scoped-cross-tab",
    credentials: "memory-only-never-broadcast-or-persisted",
  });
  return receipt;
}

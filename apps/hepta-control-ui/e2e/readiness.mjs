import { randomUUID } from "node:crypto";
import { expect } from "@playwright/test";

const READINESS_SCHEMA = "hepta.ui-control.readiness.v1";
const NAVIGATION_PARAMETER = "ui-control-navigation";

function isExpectedNavigationInterruption(error) {
  const message = String(error?.message ?? error);
  return [
    "Execution context was destroyed",
    "navigation",
    "frame was detached",
    "Target page, context or browser has been closed",
  ].some(fragment => message.includes(fragment));
}

async function navigateControlConsole(page) {
  const navigationId = `navigation:${randomUUID()}`;
  const relativeUrl = `/?${NAVIGATION_PARAMETER}=${encodeURIComponent(navigationId)}`;
  const response = await page.context().request.get(relativeUrl);
  const httpStatus = response.status();
  const targetUrl = response.url();
  const httpOk = response.ok();
  await response.dispose();

  expect(httpOk, `navigation preflight failed with HTTP ${httpStatus}`).toBeTruthy();

  // Firefox can render and finish application startup while a protocol-level
  // page.goto(..., waitUntil: "commit") promise remains pending. Initiate the
  // navigation without treating a browser lifecycle event as application
  // readiness, then wait for the application's immutable readiness receipt.
  try {
    await page.evaluate(url => globalThis.location.replace(url), targetUrl);
  } catch (error) {
    if (!isExpectedNavigationInterruption(error)) throw error;
  }

  await expect.poll(
    async () => {
      try {
        return await page.evaluate(
          ({ navigationId: expectedId, parameter }) => {
            const currentId = new URL(globalThis.location.href).searchParams.get(parameter);
            const marker = document.documentElement.dataset.uiControlReady;
            const phase = globalThis.__heptaUiControlReadiness?.phase;
            return currentId === expectedId &&
              (marker === "true" || marker === "failed" || phase === "failed");
          },
          { navigationId, parameter: NAVIGATION_PARAMETER },
        );
      } catch {
        // The old execution context may disappear between navigation and the
        // first evaluation. Poll the new document rather than sleeping.
        return false;
      }
    },
    {
      timeout: 30_000,
      message: `ui.control did not acknowledge navigation ${navigationId}`,
    },
  ).toBe(true);

  const receipt = await page.evaluate(() =>
    JSON.parse(JSON.stringify(globalThis.__heptaUiControlReadiness ?? null)),
  );
  expect(receipt, "the browser application must publish a readiness receipt").not.toBeNull();

  return Object.freeze({
    ...receipt,
    navigationAck: Object.freeze({
      id: navigationId,
      httpStatus,
      finalUrl: page.url(),
      applicationReady: receipt.phase === "ready",
    }),
  });
}

export async function loadControlConsole(page) {
  const receipt = await navigateControlConsole(page);
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

export async function loadFailedControlConsole(page) {
  const receipt = await navigateControlConsole(page);
  // A loader failure occurs before Rust can publish its full ready schema.
  // Observe the current document's fixed fail-closed receipt, never "load".
  expect(receipt.phase).toBe("failed");
  expect(receipt.errorCode).toBe("UI_CONTROL_STARTUP");
  expect(receipt.navigationAck.applicationReady).toBe(false);
  return receipt;
}

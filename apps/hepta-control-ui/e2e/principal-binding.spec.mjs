import { expect, test } from "@playwright/test";
import { loadControlConsole } from "./readiness.mjs";

async function bindTabSession(page, { identityId, sessionId }) {
  const rewriteSession = async route => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, identityId, sessionId } });
  };
  const rewriteView = async route => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, sessionId } });
  };

  await page.route("**/api/ui-control/v1/session/connect", rewriteSession);
  await page.route("**/api/ui-control/v1/session/refresh", rewriteSession);
  await page.route("**/api/ui-control/v1/view", rewriteView);
}

async function load(page) {
  const receipt = await loadControlConsole(page);
  expect(receipt.navigationAck.applicationReady).toBe(true);
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Request start", exact: true }))
    .toBeEnabled();
}

async function submit(page, reason) {
  await page.getByLabel("Reason", { exact: true }).fill(reason);
  await page.getByRole("button", { name: "Request start", exact: true }).click();
  await page.getByRole("button", { name: "Submit request", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
}

test.beforeEach(async ({ request }) => {
  expect((await request.get("/__test__/reset")).ok()).toBeTruthy();
});

test("fixture ledger binds one operation identity to one admitted session", async ({
  page,
  context,
  request,
}) => {
  const other = await context.newPage();
  await Promise.all([
    bindTabSession(page, {
      identityId: "operator-first",
      sessionId: "session-first",
    }),
    bindTabSession(other, {
      identityId: "operator-second",
      sessionId: "session-second",
    }),
  ]);
  await Promise.all([load(page), load(other)]);
  await Promise.all([
    submit(page, "Bind the first operation to the first session."),
    submit(other, "Bind the second operation to the second session."),
  ]);

  const state = await (await request.get("/__test__/state")).json();
  expect(state.requestCount).toBe(2);
  expect(state.operations).toHaveLength(2);
  expect(new Set(state.operations.map(operation => operation.binding.sessionId)))
    .toEqual(new Set(["session-first", "session-second"]));

  const first = state.operations.find(
    operation => operation.binding.sessionId === "session-first",
  );
  expect(first).toBeTruthy();
  expect(first.binding.protocolVersion).toBe("hepta.ui-control.v1");
  expect(first.binding.connectionGeneration).toBe(1);
  expect(first.binding.semanticDigest).toBe(first.semanticDigest);
  expect(first.binding.snapshotDigest).toMatch(/^[0-9a-f]{64}$/u);

  const allowedQuery = new URLSearchParams({
    sessionId: first.binding.sessionId,
    connectionGeneration: String(first.binding.connectionGeneration),
    semanticDigest: first.binding.semanticDigest,
  });
  const allowed = await request.get(
    `/api/ui-control/v1/operations/${encodeURIComponent(first.operationId)}?${allowedQuery}`,
  );
  expect(allowed.status()).toBe(200);
  expect((await allowed.json()).operationId).toBe(first.operationId);

  const deniedQuery = new URLSearchParams({
    sessionId: "session-second",
    connectionGeneration: String(first.binding.connectionGeneration),
    semanticDigest: first.binding.semanticDigest,
  });
  const denied = await request.get(
    `/api/ui-control/v1/operations/${encodeURIComponent(first.operationId)}?${deniedQuery}`,
  );
  expect(denied.status()).toBe(403);

  const rebound = await request.post("/api/ui-control/v1/operations", {
    headers: { "x-hepta-csrf-token": "csrf-fixture-token" },
    data: {
      ...first.binding,
      operationId: first.operationId,
      sessionId: "session-second",
    },
  });
  expect(rebound.status()).toBe(409);
  expect((await (await request.get("/__test__/state")).json()).requestCount)
    .toBe(2);

  await other.close();
});

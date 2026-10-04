import assert from "node:assert/strict";
import test from "node:test";
import { loadControlConsole, loadFailedControlConsole } from "../e2e/readiness.mjs";

const ready = {
  schema: "hepta.ui-control.readiness.v1", phase: "ready", tabId: "tab:fixture",
  stateOwnership: {
    activeSession: "tab-private", selectionAndFocus: "tab-private",
    recoveryRecords: "endpoint-protocol-identity-scoped-cross-tab",
    leaderAndClaims: "scope-scoped-cross-tab",
    credentials: "memory-only-never-broadcast-or-persisted",
  },
};
const failed = { phase: "failed", errorCode: "UI_CONTROL_STARTUP" };

// Unit-test the navigation/receipt contract without claiming browser execution.
function pageFixture(receipt, { status = 200, navigationError } = {}) {
  let url = "about:blank";
  const calls = { disposed: 0, navigated: 0, acknowledged: [] };
  return {
    calls,
    context: () => ({ request: { get: async relative => ({
      status: () => status, ok: () => status === 200,
      url: () => `http://127.0.0.1:4174${relative}`,
      dispose: async () => { calls.disposed++; },
    }) } }),
    goto: () => { throw new Error("must not wait for a browser load event"); },
    url: () => url,
    evaluate: async (_fn, argument) => {
      if (typeof argument === "string") {
        url = argument; calls.navigated++;
        if (navigationError) throw navigationError;
        return;
      }
      if (argument) {
        assert.equal(new URL(url).searchParams.get(argument.parameter), argument.navigationId);
        calls.acknowledged.push(argument.navigationId);
        return true;
      }
      return structuredClone(receipt);
    },
  };
}

test("loader failure acknowledges this navigation without a browser load event", async () => {
  const page = pageFixture(failed);
  const receipt = await loadFailedControlConsole(page);
  assert.equal(receipt.phase, "failed");
  assert.equal(receipt.navigationAck.applicationReady, false);
  assert.equal(receipt.navigationAck.finalUrl, page.url());
  assert.deepEqual(page.calls.acknowledged, [receipt.navigationAck.id]);
  assert.equal(page.calls.disposed, 1);
  assert.equal(page.calls.navigated, 1);
  assert(Object.isFrozen(receipt));
  assert(Object.isFrozen(receipt.navigationAck));
});

test("normal readiness retains schema, identity, and ownership checks", async () => {
  const receipt = await loadControlConsole(pageFixture(ready));
  assert.equal(receipt.navigationAck.applicationReady, true);
  for (const changed of [{ ...ready, schema: "wrong" }, { ...ready, tabId: "wrong" }, { ...ready, stateOwnership: {} }]) {
    await assert.rejects(loadControlConsole(pageFixture(changed)));
  }
});

test("ready and failed receipts cannot substitute for each other", async () => {
  await assert.rejects(loadControlConsole(pageFixture(failed)));
  await assert.rejects(loadFailedControlConsole(pageFixture(ready)));
  await assert.rejects(loadFailedControlConsole(pageFixture({ ...failed, errorCode: "other" })));
});

test("failed HTTP preflight and unexpected navigation errors remain fatal", async () => {
  const page = pageFixture(failed, { status: 503 });
  await assert.rejects(loadFailedControlConsole(page));
  assert.equal(page.calls.navigated, 0);
  assert.equal(page.calls.disposed, 1);
  const error = new Error("unexpected evaluation defect");
  await assert.rejects(loadFailedControlConsole(pageFixture(failed, { navigationError: error })), value => value === error);
});

test("expected context loss still requires a fresh navigation acknowledgement", async () => {
  const page = pageFixture(failed, { navigationError: new Error("Execution context was destroyed") });
  const first = await loadFailedControlConsole(page);
  const second = await loadFailedControlConsole(page);
  assert.notEqual(first.navigationAck.id, second.navigationAck.id);
  assert.deepEqual(page.calls.acknowledged, [first.navigationAck.id, second.navigationAck.id]);
});

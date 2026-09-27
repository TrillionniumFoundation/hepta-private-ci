import assert from "node:assert/strict";
import test from "node:test";

import { ReplayProbeBrowserHost } from "../src/replay-probe-host.js";
import { admitNewOperation } from "../src/runtime-contract.js";

function hostFixture() {
  const calls = [];
  const originalReceipt = Object.freeze({
    kind: "BrowserEffectObservationV1",
    operationId: "operation.1",
    status: "indeterminate",
  });
  return {
    calls,
    originalReceipt,
    host: {
      async openProfile(input) { return input; },
      async admitEffectGrant(input) { return input; },
      async observePage(input) { return input; },
      async navigateOrAct(input) {
        calls.push(["navigateOrAct", input]);
        return originalReceipt;
      },
      async reconcileOperation(input) {
        calls.push(["reconcileOperation", input]);
        return { status: "reconciled" };
      },
      async reconcilePersistedOperation(input) { return input; },
      async closeProfile(input) { return input; },
    },
  };
}

test("replay-only reconciliation returns the original receipt without live reconciliation", async () => {
  const fixture = hostFixture();
  const host = new ReplayProbeBrowserHost(fixture.host);
  const input = { operationId: "operation.1", replayOnly: true };
  const receipt = await host.reconcileOperation(input);
  assert.equal(receipt, fixture.originalReceipt);
  assert.deepEqual(fixture.calls, [["navigateOrAct", input]]);
});

test("ordinary reconciliation still uses the live observer path", async () => {
  const fixture = hostFixture();
  const host = new ReplayProbeBrowserHost(fixture.host);
  const input = { operationId: "operation.1" };
  const receipt = await host.reconcileOperation(input);
  assert.equal(receipt.status, "reconciled");
  assert.deepEqual(fixture.calls, [["reconcileOperation", input]]);
});

test("a replay probe that reaches new-operation admission proves absence without executing", () => {
  assert.throws(
    () => admitNewOperation({}, { replayOnly: true }, 1),
    /operation has not crossed the browser effect boundary/,
  );
  assert.throws(
    () => admitNewOperation({}, { replayOnly: "yes" }, 1),
    /replayOnly must be boolean/,
  );
});

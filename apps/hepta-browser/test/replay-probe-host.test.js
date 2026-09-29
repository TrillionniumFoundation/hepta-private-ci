import assert from "node:assert/strict";
import test from "node:test";

import {
  REPLAY_PROBE_RESULT_KIND,
  ReplayProbeBrowserHost,
} from "../src/replay-probe-host.js";
import {
  REPLAY_PROBE_ABSENCE_CODE,
  admitNewOperation,
} from "../src/runtime-contract.js";

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

test("replay-only reconciliation returns a closed present envelope without live reconciliation", async () => {
  const fixture = hostFixture();
  const host = new ReplayProbeBrowserHost(fixture.host);
  const input = { operationId: "operation.1", replayOnly: true };
  const result = await host.reconcileOperation(input);
  assert.deepEqual(result, {
    kind: REPLAY_PROBE_RESULT_KIND,
    status: "present",
    receipt: fixture.originalReceipt,
  });
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

test("a replay probe that reaches new-operation admission emits the stable absence code", () => {
  assert.throws(
    () => admitNewOperation({}, { replayOnly: true }, 1),
    (error) => {
      assert.match(error.message, /operation has not crossed/);
      assert.equal(error.code, REPLAY_PROBE_ABSENCE_CODE);
      assert.equal(Object.keys(error).includes("code"), false);
      return true;
    },
  );
  assert.throws(
    () => admitNewOperation({}, { replayOnly: "yes" }, 1),
    /replayOnly must be boolean/,
  );
});

test("only exact typed absence becomes an absent envelope", async () => {
  const typed = hostFixture();
  typed.host.navigateOrAct = async () => {
    const error = new TypeError("diagnostic wording is not protocol");
    error.code = REPLAY_PROBE_ABSENCE_CODE;
    throw error;
  };
  assert.deepEqual(
    await new ReplayProbeBrowserHost(typed.host).reconcileOperation({
      operationId: "operation.absent",
      replayOnly: true,
    }),
    {
      kind: REPLAY_PROBE_RESULT_KIND,
      status: "absent",
      absenceCode: REPLAY_PROBE_ABSENCE_CODE,
    },
  );

  const untyped = hostFixture();
  untyped.host.navigateOrAct = async () => {
    throw new TypeError("operation has not crossed the browser effect boundary");
  };
  await assert.rejects(
    new ReplayProbeBrowserHost(untyped.host).reconcileOperation({
      operationId: "operation.untyped",
      replayOnly: true,
    }),
    /operation has not crossed/,
  );
});

import assert from "node:assert/strict";
import test from "node:test";

import {
  REPLAY_PROBE_ABSENCE_CODE,
  admitNewOperation,
} from "../src/runtime-contract.js";
import {
  REPLAY_PROBE_RESULT_KIND,
  ReplayProbeBrowserHost,
} from "../src/replay-probe-host.js";

function hostWithNavigate(navigateOrAct) {
  const passthrough = async () => ({ ok: true });
  return {
    openProfile: passthrough,
    admitEffectGrant: passthrough,
    observePage: passthrough,
    navigateOrAct,
    reconcileOperation: passthrough,
    reconcilePersistedOperation: passthrough,
    closeProfile: passthrough,
  };
}

test("owner emits a non-enumerable stable code for replay absence", () => {
  assert.throws(
    () => admitNewOperation({}, { replayOnly: true }, 1),
    (error) => {
      assert.equal(error.code, REPLAY_PROBE_ABSENCE_CODE);
      assert.equal(Object.keys(error).includes("code"), false);
      return true;
    },
  );
});

test("replay probe wraps existing receipts in a closed present envelope", async () => {
  const receipt = Object.freeze({ operationId: "operation.1", status: "succeeded" });
  const probe = new ReplayProbeBrowserHost(
    hostWithNavigate(async () => receipt),
  );
  assert.deepEqual(
    await probe.reconcileOperation({ replayOnly: true }),
    {
      kind: REPLAY_PROBE_RESULT_KIND,
      status: "present",
      receipt,
    },
  );
});

test("only the exact owner-issued absence code becomes an absent envelope", async () => {
  const typed = new ReplayProbeBrowserHost(
    hostWithNavigate(async () => {
      const error = new TypeError("diagnostic text may change");
      error.code = REPLAY_PROBE_ABSENCE_CODE;
      throw error;
    }),
  );
  assert.deepEqual(
    await typed.reconcileOperation({ replayOnly: true }),
    {
      kind: REPLAY_PROBE_RESULT_KIND,
      status: "absent",
      absenceCode: REPLAY_PROBE_ABSENCE_CODE,
    },
  );

  const untyped = new ReplayProbeBrowserHost(
    hostWithNavigate(async () => {
      throw new TypeError("operation has not crossed the browser effect boundary");
    }),
  );
  await assert.rejects(
    untyped.reconcileOperation({ replayOnly: true }),
    /operation has not crossed/,
  );
});

test("ordinary reconciliation remains on the original read path", async () => {
  let reconcileCalls = 0;
  const host = hostWithNavigate(async () => {
    throw new Error("navigate path must not run");
  });
  host.reconcileOperation = async () => {
    reconcileCalls += 1;
    return { status: "indeterminate" };
  };
  const probe = new ReplayProbeBrowserHost(host);
  assert.deepEqual(await probe.reconcileOperation({}), { status: "indeterminate" });
  assert.equal(reconcileCalls, 1);
});

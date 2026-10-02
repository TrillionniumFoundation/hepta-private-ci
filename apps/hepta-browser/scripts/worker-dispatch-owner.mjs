// The argument must be built from build-dispatch-source-harness.py. This tests
// the real owner and extracted Rust admission/receipt path, not Servo or IPC.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { browserActionDigest } from "../src/action.js";
import { MemoryBrowserOperationJournal } from "../src/journal.js";
import { BrowserProfileHost } from "../src/runtime.js";

const executable = process.argv[2];
assert.ok(executable, "pass the compiled dispatch source harness executable");
const sourceOrigin = "https://example.com";
const targetOrigin = "https://other.example";
const digest = "1".repeat(64);
const identity = {
  profileId: "profile.1",
  principalId: "principal.1",
  generation: 1,
};

for (const destinationOrigin of [sourceOrigin, targetOrigin]) {
  const typedAction = {
    kind: "download",
    url: `${destinationOrigin}/file`,
    maxBytes: 1024,
  };
  const finalPayloadDigest = browserActionDigest(typedAction);
  let authorizations = 0;
  let dispatches = 0;
  let workerResult;
  const journal = new MemoryBrowserOperationJournal();
  const host = new BrowserProfileHost({
    journal,
    driverCallTimeoutMs: 3000,
    authority: {
      async withVerifiedUse(request, consume) {
        authorizations += 1;
        return consume({
          authorized: true,
          authorityEpoch: 1,
          requestDigest: request.requestDigest,
          witnessDigest: digest,
        });
      },
    },
    driver: {
      async start() {
        return { started: true, processId: "servo.fixture.1" };
      },
      async observe() {
        return {
          pageGeneration: 1,
          documentDigest: digest,
          origin: sourceOrigin,
        };
      },
      async dispatch(input) {
        dispatches += 1;
        const run = spawnSync(executable, {
          input: JSON.stringify(input),
          encoding: "utf8",
          timeout: 2000,
          maxBuffer: 65536,
        });
        assert.equal(run.status, 0, run.stderr);
        workerResult = JSON.parse(run.stdout);
        assert.equal(workerResult.reserved, 1);
        assert.deepEqual(
          {
            status: workerResult.dispatch.status,
            terminalObserved: workerResult.dispatch.terminalObserved,
          },
          { status: "failed", terminalObserved: true },
        );
        return { terminalObserved: false };
      },
      async reconcile() {
        return workerResult.reconcile;
      },
      async stop() {
        return { stopped: true };
      },
    },
  });
  const expiresAtMs = Date.now() + 10000;
  await host.openProfile({
    ...identity,
    manifestDigest: digest,
    grantDigest: digest,
    expiresAtMs,
    allowedOrigins: [sourceOrigin, targetOrigin],
    effectGrants: [
      {
        grantDigest: digest,
        action: "download",
        destinationOrigin,
        finalPayloadDigest,
        authorityEpoch: 1,
        expiresAtMs,
      },
    ],
  });
  await host.observePage({ ...identity, observationBudget: 128 });
  const request = {
    ...identity,
    operationId: "operation.1",
    pageGeneration: 1,
    typedAction,
    destinationOrigin,
    finalPayloadDigest,
    effectGrantDigest: digest,
    authorityEpoch: 1,
    deadlineMs: expiresAtMs,
  };
  assert.equal((await host.navigateOrAct(request)).terminalObserved, false);
  const terminal = await host.reconcileOperation(request);
  assert.deepEqual(
    { status: terminal.status, terminalObserved: terminal.terminalObserved },
    { status: "failed", terminalObserved: true },
  );
  assert.deepEqual(await host.navigateOrAct(request), terminal);
  assert.equal((await host.closeProfile(identity)).terminalObserved, true);
  const records = await journal.listOperations(
    identity.profileId,
    identity.generation,
  );
  assert.equal(records.length, 1);
  assert.equal(records[0].terminalObserved, true);
  assert.deepEqual(
    { authorizations, dispatches },
    { authorizations: 1, dispatches: 1 },
  );
}
console.log(
  "PASS owner -> extracted Rust download refusal -> reconciliation -> replay -> close (same/cross origin)",
);

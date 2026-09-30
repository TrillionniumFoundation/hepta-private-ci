import assert from "node:assert/strict";
import { generateKeyPairSync, sign } from "node:crypto";
import test from "node:test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  FilePersistedEffectReconciler,
  persistedEffectObservationSigningBytes,
} from "../src/persisted-reconciler.js";

const REQUEST = "1".repeat(64);
const SEMANTIC = "2".repeat(64);
const OUTCOME = "3".repeat(64);
const FRONTIER = "4".repeat(64);

function observerKeypair() {
  const pair = generateKeyPairSync("ed25519");
  const spki = pair.publicKey.export({ format: "der", type: "spki" });
  return {
    privateKey: pair.privateKey,
    verifyingKeyHex: spki.subarray(spki.length - 32).toString("hex"),
  };
}

function signedReceipt(receipt, privateKey) {
  return {
    ...receipt,
    signature: sign(
      null,
      persistedEffectObservationSigningBytes(receipt),
      privateKey,
    ).toString("hex"),
  };
}

test("authenticated persisted receipt terminalizes only the exact durable identity", async () => {
  const root = await mkdtemp(join(tmpdir(), "hepta-persisted-reconcile-"));
  await new Promise((resolve, reject) =>
    import("node:fs").then(({ chmod }) =>
      chmod(root, 0o700, (error) => (error ? reject(error) : resolve())),
    ),
  );
  const keys = observerKeypair();
  const observerId = "business-observer.1";
  const reconciler = new FilePersistedEffectReconciler(root, {
    observerId,
    verifyingKeyHex: keys.verifyingKeyHex,
    minimumObserverGeneration: 3,
    minimumObservedAtUnixMs: 1_700_000_000_000,
    currentFrontierDigest: FRONTIER,
    now: () => 1_800_000_000_100,
    maxFutureSkewMs: 1_000,
  });
  const input = {
    profileId: "profile.1",
    profileGeneration: 7,
    operationId: "operation.1",
    requestDigest: REQUEST,
    semanticDigest: SEMANTIC,
  };
  const missing = await reconciler.observe(input);
  assert.equal(missing.terminalObserved, false);

  const unsigned = {
    schema: "hepta.browser.persisted-effect-observation.v2",
    version: 2,
    observerId,
    observerGeneration: 3,
    observedAtUnixMs: 1_800_000_000_000,
    frontierDigest: FRONTIER,
    profileId: input.profileId,
    profileGeneration: input.profileGeneration,
    operationId: input.operationId,
    requestDigest: input.requestDigest,
    semanticDigest: input.semanticDigest,
    terminalObserved: true,
    status: "succeeded",
    outcomeDigest: OUTCOME,
  };
  const receipt = signedReceipt(unsigned, keys.privateKey);
  const path = join(root, "profile.1.7.operation.1.json");
  await writeFile(path, JSON.stringify(receipt), { mode: 0o600 });
  const observed = await reconciler.observe(input);
  assert.equal(observed.terminalObserved, true);
  assert.equal(observed.status, "succeeded");
  assert.equal(observed.outcomeDigest, OUTCOME);
  assert.equal(observed.observerId, observerId);
  assert.equal(observed.observerGeneration, 3);
  assert.equal(observed.frontierDigest, FRONTIER);
  assert.match(observed.evidenceDigest, /^[0-9a-f]{64}$/);

  await writeFile(
    path,
    JSON.stringify({ ...receipt, semanticDigest: "5".repeat(64) }),
    { mode: 0o600 },
  );
  await assert.rejects(reconciler.observe(input), /does not bind/);

  await writeFile(
    path,
    JSON.stringify({ ...receipt, outcomeDigest: "6".repeat(64) }),
    { mode: 0o600 },
  );
  await assert.rejects(reconciler.observe(input), /signature is not authentic/);

  await writeFile(
    path,
    JSON.stringify({ ...receipt, observerId: "different-observer" }),
    { mode: 0o600 },
  );
  await assert.rejects(
    reconciler.observe(input),
    /observer is not the configured authority/,
  );

  for (const [mutation, pattern] of [
    [{ observerGeneration: 2 }, /observer generation is stale/],
    [{ observedAtUnixMs: 1_699_999_999_999 }, /observation time is stale/],
    [{ frontierDigest: "5".repeat(64) }, /frontier is stale/],
    [{ observedAtUnixMs: 1_800_000_001_101 }, /observation time is in the future/],
  ]) {
    const stale = signedReceipt({ ...unsigned, ...mutation }, keys.privateKey);
    await writeFile(path, JSON.stringify(stale), { mode: 0o600 });
    await assert.rejects(reconciler.observe(input), pattern);
  }
  await rm(root, { recursive: true, force: true });
});

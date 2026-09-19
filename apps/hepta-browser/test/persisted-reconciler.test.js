import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { FilePersistedEffectReconciler } from "../src/persisted-reconciler.js";

const REQUEST = "1".repeat(64);
const SEMANTIC = "2".repeat(64);
const OUTCOME = "3".repeat(64);

test("trusted persisted receipt terminalizes only the exact durable identity", async () => {
  const root = await mkdtemp(join(tmpdir(), "hepta-persisted-reconcile-"));
  await new Promise((resolve, reject) =>
    import("node:fs").then(({ chmod }) =>
      chmod(root, 0o700, (error) => (error ? reject(error) : resolve())),
    ),
  );
  const reconciler = new FilePersistedEffectReconciler(root);
  const input = {
    profileId: "profile.1",
    profileGeneration: 7,
    operationId: "operation.1",
    requestDigest: REQUEST,
    semanticDigest: SEMANTIC,
  };
  const missing = await reconciler.observe(input);
  assert.equal(missing.terminalObserved, false);

  const receipt = {
    schema: "hepta.browser.persisted-effect-observation.v1",
    version: 1,
    profileId: input.profileId,
    profileGeneration: input.profileGeneration,
    operationId: input.operationId,
    requestDigest: input.requestDigest,
    semanticDigest: input.semanticDigest,
    terminalObserved: true,
    status: "succeeded",
    outcomeDigest: OUTCOME,
  };
  const path = join(root, "profile.1.7.operation.1.json");
  await writeFile(path, JSON.stringify(receipt), { mode: 0o600 });
  const observed = await reconciler.observe(input);
  assert.equal(observed.terminalObserved, true);
  assert.equal(observed.status, "succeeded");
  assert.equal(observed.outcomeDigest, OUTCOME);

  await writeFile(
    path,
    JSON.stringify({ ...receipt, semanticDigest: "4".repeat(64) }),
    { mode: 0o600 },
  );
  await assert.rejects(reconciler.observe(input), /does not bind/);
  await rm(root, { recursive: true, force: true });
});

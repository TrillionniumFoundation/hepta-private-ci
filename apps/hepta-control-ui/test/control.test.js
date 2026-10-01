import assert from "node:assert/strict";
import test from "node:test";
import {
  UI_CONTROL_ERROR_CODES,
  UiControlError,
  buildLocalOperationProposalFromCanonicalJson,
  buildOperationIntent,
  canonicalJson,
  digestCanonical,
  digestOperationIntent,
  parseCanonicalJson,
  projectRuntime,
  projectRuntimeFromLocalCanonicalJson,
} from "../src/index.js";
import { DIGEST_A, DIGEST_B } from "./helpers.js";

const runtime = {
  generation: 2,
  revision: 3,
  modules: [
    { id: "z.module", status: "ready", revision: 1, semanticDigest: DIGEST_A },
    { id: "a.module", status: "degraded", revision: 2, semanticDigest: DIGEST_B },
  ],
};

test("runtime projection is canonical, sorted, and deeply immutable", () => {
  const projected = projectRuntime(runtime);
  assert.deepEqual(projected.modules.map(module => module.id), ["a.module", "z.module"]);
  assert.equal(Object.isFrozen(projected), true);
  assert.equal(Object.isFrozen(projected.modules), true);
  assert.equal(Object.isFrozen(projected.modules[0]), true);
  assert.throws(() => projected.modules.push(runtime.modules[0]), TypeError);
});

test("canonical JSON rejects unsafe integers, prototype keys, bidi, and non-canonical source", () => {
  assert.throws(
    () => canonicalJson({ value: Number.MAX_SAFE_INTEGER + 1 }),
    error => error instanceof UiControlError && error.code === UI_CONTROL_ERROR_CODES.INVALID_INPUT,
  );
  const dangerous = Object.create(null);
  Object.defineProperty(dangerous, "__proto__", { value: "x", enumerable: true });
  assert.throws(() => canonicalJson(dangerous), /forbidden object key/);
  assert.throws(() => canonicalJson({ label: "safe\u202eevil" }), /bidi/);
  assert.throws(() => parseCanonicalJson('{"b":1,"a":2}'), /canonical JSON/);
  assert.deepEqual(parseCanonicalJson('{"a":2,"b":1}'), { a: 2, b: 1 });
});

test("digest domains separate otherwise identical values", async () => {
  const one = await digestCanonical("hepta.ui-control.one.v1", { a: 1 });
  const two = await digestCanonical("hepta.ui-control.two.v1", { a: 1 });
  assert.match(one, /^[0-9a-f]{64}$/);
  assert.notEqual(one, two);
});

test("operation digest binds action, target, generation, revision, and reason", async () => {
  const intent = buildOperationIntent({
    action: "request_reconcile",
    targetId: "runtime.agentd",
    generation: 7,
    displayedRevision: 11,
    reason: "Recover the degraded worker.",
  });
  const digest = await digestOperationIntent(intent);
  assert.match(digest, /^[0-9a-f]{64}$/);
  assert.notEqual(
    digest,
    await digestOperationIntent({ ...intent, displayedRevision: 12 }),
  );
});

test("local canonical JSON fixture paths preserve strict boundaries", () => {
  const text = canonicalJson(runtime);
  const projected = projectRuntimeFromLocalCanonicalJson(text);
  assert.equal(projected.generation, 2);
  const proposal = buildLocalOperationProposalFromCanonicalJson(
    canonicalJson({
      action: "request_reconcile",
      displayedRevision: 3,
      generation: 2,
      reason: "Qualification fixture.",
      targetId: "runtime.agentd",
    }),
  );
  assert.equal(proposal.targetId, "runtime.agentd");
});

test("duplicate module ids and unknown operation actions are rejected", () => {
  assert.throws(
    () => projectRuntime({ ...runtime, modules: [runtime.modules[0], runtime.modules[0]] }),
    /duplicate module id/,
  );
  assert.throws(
    () => buildOperationIntent({
      action: "execute_now",
      targetId: "runtime.agentd",
      generation: 1,
      displayedRevision: 1,
      reason: "No.",
    }),
    /not registered/,
  );
});

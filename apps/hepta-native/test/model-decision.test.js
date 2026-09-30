import test from "node:test";
import assert from "node:assert/strict";
import { clipboardChoiceFromModel } from "../qualification/model-decision.mjs";
const one = (n, i) => Array.from({ length: n }, (_, j) => j === i ? 1 : 0);
const input = () => ({ schema: "hepta.model-native-probe-input.v2", requestId: "test.one",
  replySha256: "a".repeat(64), projectionSha256: "b".repeat(64), headManifestSha256: "c".repeat(64),
  baseSnapshotDigest: "d".repeat(64), modelSupported: true, probabilities: { action: one(6, 2), target: one(4, 3),
    disposition: one(6, 0), postcondition: one(6, 2), ood: one(2, 0) },
  targets: Array.from({ length: 4 }, (_, i) => ({ referenceId: `reference.${i}`, generation: 1, text: `nonsecret-${i}` })) });

test("selected target comes from the model pointer, not an expected label", () => {
  const value = input(); const selected = clipboardChoiceFromModel(value, 1);
  assert.equal(selected.referenceId, "reference.3"); assert.equal(selected.text, "nonsecret-3");
  assert.equal(selected.authorityGranted, false);
  value.probabilities.target = one(4, 0);
  assert.equal(clipboardChoiceFromModel(value, 1).referenceId, "reference.0");
});
test("wrong action, disposition and postcondition all abstain", () => {
  for (const field of ["action", "disposition", "postcondition"]) {
    const value = input(); value.probabilities[field] = one(6, 5);
    assert.equal(clipboardChoiceFromModel(value, 1).status, "abstained");
  }
});
test("uncertain and OOD decisions cannot cross the qualification effect boundary", () => {
  const value = input(); value.probabilities.target = [.3, .3, .2, .2];
  assert.equal(clipboardChoiceFromModel(value, 1).status, "abstained");
  value.probabilities.target = one(4, 0); value.probabilities.ood = [.01, .99];
  assert.equal(clipboardChoiceFromModel(value, 1).status, "abstained");
});
test("changed target generation and duplicate references reject", () => {
  const value = input(); value.targets[1].generation = 2;
  assert.throws(() => clipboardChoiceFromModel(value, 1), /stale/);
  value.targets[1].generation = 1; value.targets[1].referenceId = value.targets[0].referenceId;
  assert.throws(() => clipboardChoiceFromModel(value, 1), /duplicate/);
});
test("NaN, infinity, negative mass and misnormalization reject", () => {
  for (const number of [NaN, Infinity, -1, 2, .2]) {
    const value = input(); value.probabilities.action[0] = number;
    assert.throws(() => clipboardChoiceFromModel(value, 1), /probability/);
  }
});
test("malformed bindings and unknown or executable fields reject", () => {
  const value = input(); value.nativeCode = "00";
  assert.throws(() => clipboardChoiceFromModel(value, 1), /field/);
  delete value.nativeCode; value.replySha256 = "0".repeat(64);
  assert.throws(() => clipboardChoiceFromModel(value, 1), /digest/);
});
test("getters cannot substitute target data during validation", () => {
  const value = input(); Object.defineProperty(value.targets[0], "text", { get() { throw new Error("executed getter"); }, enumerable: true });
  assert.throws(() => clipboardChoiceFromModel(value, 1), /own data/);
});

test("sparse probability arrays and nonstring identifiers reject", () => {
  const value = input(); delete value.probabilities.target[1];
  assert.throws(() => clipboardChoiceFromModel(value, 1), /probability/);
  value.probabilities.target = one(4, 1); value.requestId = 12;
  assert.throws(() => clipboardChoiceFromModel(value, 1), /identity/);
});

test("own array reducers cannot bypass probability validation", () => {
  const value = input();
  value.probabilities.action = [NaN, 0, 1, 0, 0, 0];
  value.probabilities.action.some = () => false;
  value.probabilities.action.reduce = (_fn, initial) => initial === 0 ? 1 : 2;
  assert.throws(() => clipboardChoiceFromModel(value, 1), /probability|array/);
});
test("array method accessors are rejected without being executed", () => {
  const value = input(); let calls = 0;
  Object.defineProperty(value.probabilities.action, "some", { get() { calls++; return () => false; } });
  assert.throws(() => clipboardChoiceFromModel(value, 1), /probability|array/);
  assert.equal(calls, 0);
});
test("target array getters never run even when returning a legal target", () => {
  const value = input(); const target = value.targets[3]; let calls = 0;
  Object.defineProperty(value.targets, "3", { get() { calls++; return target; }, enumerable: true });
  assert.throws(() => clipboardChoiceFromModel(value, 1), /target|array/);
  assert.equal(calls, 0);
});
test("target iterators cannot hide duplicate or stale targets", () => {
  const value = input(); const allowed = value.targets.map((target) => ({ ...target }));
  value.targets[3].generation = 2;
  value.targets[Symbol.iterator] = function* () { yield* allowed; };
  assert.throws(() => clipboardChoiceFromModel(value, 1), /target|array/);
});
test("custom prototypes and non-data records are not admitted", () => {
  for (const record of ["packet", "probabilities", "target"]) {
    const value = input();
    Object.setPrototypeOf(record === "packet" ? value : record === "target" ? value.targets[0] : value.probabilities, { hidden: true });
    assert.throws(() => clipboardChoiceFromModel(value, 1), /plain|data/);
  }
});
test("returned choices keep validated snapshots after caller mutations", () => {
  const value = input(); const selected = clipboardChoiceFromModel(value, 1);
  value.targets[3].text = "substituted"; value.probabilities.target[3] = 0;
  assert.equal(selected.text, "nonsecret-3"); assert.ok(Object.isFrozen(selected));
  value.probabilities.target = [.25, .25, .25, .25];
  const abstained = clipboardChoiceFromModel(value, 1);
  assert.ok(Object.isFrozen(abstained.predicted));
});
test("proxies are rejected before any reflective trap can run", () => {
  for (const field of ["packet", "action", "targets"]) {
    let value = input(); let traps = 0;
    const proxy = (target) => new Proxy(target, { getPrototypeOf() { traps++; throw new Error("trap ran"); }, ownKeys() { traps++; throw new Error("trap ran"); } });
    if (field === "packet") value = proxy(value);
    else if (field === "action") value.probabilities.action = proxy(value.probabilities.action);
    else value.targets = proxy(value.targets);
    assert.throws(() => clipboardChoiceFromModel(value, 1), /data|array/);
    assert.equal(traps, 0);
  }
});


test("upstream model abstention vetoes otherwise certain clipboard decisions", () => {
  const value = input(); value.modelSupported = false;
  const choice = clipboardChoiceFromModel(value, 1);
  assert.equal(choice.status, "abstained");
  assert.equal(choice.modelSupported, false);
  assert.equal(choice.confidence, 1);
  assert.equal(choice.ood, 0);
  assert.equal(choice.authorityGranted, false);
});
test("support is an explicit boolean, never a truthy value or an inferred default", () => {
  for (const support of [0, 1, null, "true", [], {}, undefined]) {
    const value = input(); value.modelSupported = support;
    assert.throws(() => clipboardChoiceFromModel(value, 1), /support/);
  }
  const missing = input(); delete missing.modelSupported;
  assert.throws(() => clipboardChoiceFromModel(missing, 1), /field/);
});
test("v1 packets cannot be silently reinterpreted with the new support contract", () => {
  const value = input(); value.schema = "hepta.model-native-probe-input.v1";
  assert.throws(() => clipboardChoiceFromModel(value, 1), /identity/);
});
test("support accessors are rejected without executing caller code", () => {
  const value = input(); let calls = 0;
  Object.defineProperty(value, "modelSupported", {get() {calls++; return true;}, enumerable: true});
  assert.throws(() => clipboardChoiceFromModel(value, 1), /own data/);
  assert.equal(calls, 0);
});
test("support true cannot bypass diagnostic thresholds or supply effect authority", () => {
  const value = input(); value.probabilities.target = [.25, .25, .25, .25];
  const choice = clipboardChoiceFromModel(value, 1);
  assert.equal(choice.status, "abstained"); assert.equal(choice.modelSupported, true);
  assert.equal(choice.authorityGranted, false);
});

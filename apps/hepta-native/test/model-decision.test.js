import test from "node:test";
import assert from "node:assert/strict";
import { clipboardChoiceFromModel } from "../qualification/model-decision.mjs";
const one = (n, i) => Array.from({ length: n }, (_, j) => j === i ? 1 : 0);
const input = () => ({ schema: "hepta.model-native-probe-input.v1", requestId: "test.one",
  replySha256: "a".repeat(64), projectionSha256: "b".repeat(64), headManifestSha256: "c".repeat(64),
  baseSnapshotDigest: "d".repeat(64), probabilities: { action: one(6, 2), target: one(4, 3),
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

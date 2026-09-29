import assert from "node:assert/strict";
import test from "node:test";
import { browserActionDigest, normalizeBrowserAction } from "../src/action.js";

test("action normalization never invokes accessor-backed semantic fields", () => {
  for (const key of ["kind", "selector", "text"]) {
    let reads = 0;
    const input = { kind: "type", selector: "#search", text: "Hepta" };
    Object.defineProperty(input, key, { enumerable: true,
      get() { reads += 1; return "changed"; } });
    assert.throws(() => normalizeBrowserAction(input), /own data fields/);
    assert.throws(() => browserActionDigest(input), /own data fields/);
    assert.equal(reads, 0);
  }
});

test("unknown hidden and symbol fields cannot cross typed action normalization", () => {
  for (const key of ["hidden", Symbol("hidden")]) {
    const input = { kind: "click", selector: "#submit" };
    Object.defineProperty(input, key, { value: "unbound", enumerable: false });
    assert.throws(() => normalizeBrowserAction(input), /own data fields/);
  }
  const inherited = Object.assign(Object.create({ hidden: "unbound" }),
    { kind: "click", selector: "#submit" });
  assert.throws(() => normalizeBrowserAction(inherited), /plain data record/);
});

test("malformed UTF-16 cannot be silently replaced in a browser effect", () => {
  for (const invalid of ["\ud800", "\udfff", "x\ud800y"]) {
    for (const action of [
      { kind: "click", selector: invalid },
      { kind: "type", selector: "#search", text: invalid },
      { kind: "focus", selector: invalid },
    ]) assert.throws(() => normalizeBrowserAction(action), /well-formed Unicode/);
  }
});

test("normal and null-prototype records keep the same canonical digest", () => {
  const input = { kind: "type", selector: "#search", text: "Hepta / 中文 / 🧠" };
  const copy = Object.assign(Object.create(null), input);
  const output = normalizeBrowserAction(copy);
  assert.deepEqual(output, input);
  assert.ok(Object.isFrozen(output));
  assert.equal(browserActionDigest(input), browserActionDigest(copy));
  input.text = "later caller mutation";
  assert.equal(output.text, "Hepta / 中文 / 🧠");
});

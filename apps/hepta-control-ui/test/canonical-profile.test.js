import assert from "node:assert/strict";
import test from "node:test";
import {
  UI_CONTROL_ERROR_CODES,
  UiControlError,
  canonicalJson,
  parseCanonicalJson,
} from "../src/index.js";

function rejectsInvalidInput(callback) {
  assert.throws(
    callback,
    error =>
      error instanceof UiControlError &&
      error.code === UI_CONTROL_ERROR_CODES.INVALID_INPUT,
  );
}

test("canonical JSON preserves RFC 8785 lexical ordering for integer-like keys", () => {
  assert.equal(
    canonicalJson({
      2: "two",
      10: "ten",
      a: "letter",
    }),
    "{\"10\":\"ten\",\"2\":\"two\",\"a\":\"letter\"}",
  );
});

test("canonical JSON rejects non-canonical integer-key transport order", () => {
  rejectsInvalidInput(() =>
    parseCanonicalJson("{\"2\":\"two\",\"10\":\"ten\"}"),
  );
  assert.deepEqual(
    parseCanonicalJson("{\"10\":\"ten\",\"2\":\"two\"}"),
    { 2: "two", 10: "ten" },
  );
});

test("canonical JSON rejects lone surrogates and unbounded limit overrides", () => {
  rejectsInvalidInput(() => canonicalJson("\ud800"));
  rejectsInvalidInput(() =>
    canonicalJson({}, { maxDepth: Number.POSITIVE_INFINITY }),
  );
  rejectsInvalidInput(() => canonicalJson({}, { unreviewedLimit: 1 }));
});

test("canonical JSON rejects sparse, accessor, custom, and symbolic container members", () => {
  const sparse = new Array(2);
  sparse[1] = "present";
  rejectsInvalidInput(() => canonicalJson(sparse));

  let getterInvoked = false;
  const accessor = [];
  Object.defineProperty(accessor, "0", {
    enumerable: true,
    get() {
      getterInvoked = true;
      return "unsafe";
    },
  });
  rejectsInvalidInput(() => canonicalJson(accessor));
  assert.equal(getterInvoked, false);

  const custom = [];
  custom.metadata = "ambiguous";
  rejectsInvalidInput(() => canonicalJson(custom));

  const symbolic = { stable: true };
  symbolic[Symbol("hidden")] = "ambiguous";
  rejectsInvalidInput(() => canonicalJson(symbolic));
});

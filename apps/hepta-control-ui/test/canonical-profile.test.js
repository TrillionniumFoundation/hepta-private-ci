import assert from "node:assert/strict";
import test from "node:test";
import {
  UI_CONTROL_ERROR_CODES,
  UiControlError,
  canonicalJson,
  parseCanonicalJson,
} from "../src/index.js";

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
  assert.throws(
    () => parseCanonicalJson("{\"2\":\"two\",\"10\":\"ten\"}"),
    error =>
      error instanceof UiControlError &&
      error.code === UI_CONTROL_ERROR_CODES.INVALID_INPUT,
  );
  assert.deepEqual(
    parseCanonicalJson("{\"10\":\"ten\",\"2\":\"two\"}"),
    { 2: "two", 10: "ten" },
  );
});

test("canonical JSON rejects lone surrogates and unbounded limit overrides", () => {
  assert.throws(
    () => canonicalJson("\ud800"),
    error =>
      error instanceof UiControlError &&
      error.code === UI_CONTROL_ERROR_CODES.INVALID_INPUT,
  );
  assert.throws(
    () => canonicalJson({}, { maxDepth: Number.POSITIVE_INFINITY }),
    error =>
      error instanceof UiControlError &&
      error.code === UI_CONTROL_ERROR_CODES.INVALID_INPUT,
  );
  assert.throws(
    () => canonicalJson({}, { unreviewedLimit: 1 }),
    error =>
      error instanceof UiControlError &&
      error.code === UI_CONTROL_ERROR_CODES.INVALID_INPUT,
  );
});

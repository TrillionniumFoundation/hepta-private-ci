import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizeTypedAction,
  typedActionDestinationOrigin,
  typedActionDigest,
} from "../src/actions.js";

test("typed navigation normalizes and binds the full payload", () => {
  const left = normalizeTypedAction({
    kind: "navigate",
    url: "https://EXAMPLE.com:443/a/../b?q=1#x",
  });
  assert.deepEqual(left, {
    kind: "navigate",
    url: "https://example.com/b?q=1#x",
  });
  assert.equal(typedActionDestinationOrigin(left), "https://example.com");
  assert.equal(typedActionDigest(left), typedActionDigest({ ...left }));
});

test("typed actions reject unknown fields, credentials, and unbounded payloads", () => {
  assert.throws(
    () => normalizeTypedAction({ kind: "click", selector: "#x", extra: true }),
    /unknown fields/,
  );
  assert.throws(
    () => normalizeTypedAction({ kind: "navigate", url: "https://u:p@example.com" }),
    /credentials/,
  );
  assert.throws(
    () => normalizeTypedAction({ kind: "type", selector: "#x", text: "x".repeat(20_000) }),
    /byte limit/,
  );
});

test("credential action carries a reference, never a raw secret field", () => {
  const action = normalizeTypedAction({
    kind: "credential_fill",
    selector: "#password",
    credentialRef: "secret.ref.1",
  });
  assert.equal(action.credentialRef, "secret.ref.1");
  assert.equal("password" in action, false);
});

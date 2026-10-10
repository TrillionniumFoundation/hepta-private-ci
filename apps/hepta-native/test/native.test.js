import assert from "node:assert/strict";
import test from "node:test";

import { buildNativeIntent, observeNativeOutcome } from "../src/native.js";

const digest = "cd".repeat(32);

function intentInput(overrides = {}) {
  return {
    operationId: "operation:1",
    subjectId: "path:1",
    action: "request_open_path",
    payloadDigest: digest,
    leasePayloadDigest: digest,
    ...overrides,
  };
}

function terminalInput(overrides = {}) {
  return {
    operationId: "operation:1",
    terminalObserved: true,
    terminalStatus: "succeeded",
    outcomeDigest: digest,
    ...overrides,
  };
}

test("native intent requires exact payload binding", () => {
  const intent = buildNativeIntent(intentInput());
  assert.deepEqual(intent, {
    kind: "NativeOperationIntentV1",
    operationId: "operation:1",
    subjectId: "path:1",
    action: "request_open_path",
    payloadDigest: digest,
    effectAuthority: false,
    filesystemAuthority: false,
    notificationAuthority: false,
  });
  assert.equal(Object.isFrozen(intent), true);
});

test("payload drift fails closed", () => {
  assert.throws(
    () => buildNativeIntent(intentInput({ leasePayloadDigest: "ab".repeat(32) })),
    /does not match/,
  );
});

test("intent rejects zero digests and missing or unknown fields", () => {
  assert.throws(
    () =>
      buildNativeIntent(
        intentInput({
          payloadDigest: "0".repeat(64),
          leasePayloadDigest: "0".repeat(64),
        }),
      ),
    /non-zero/,
  );
  assert.throws(
    () => buildNativeIntent(intentInput({ filesystemAuthority: true })),
    /missing or unknown fields/,
  );

  const missing = intentInput();
  delete missing.subjectId;
  assert.throws(() => buildNativeIntent(missing), /missing or unknown fields/);

  const symbolField = intentInput();
  symbolField[Symbol("authority")] = true;
  assert.throws(() => buildNativeIntent(symbolField), /missing or unknown fields/);

  const hiddenField = intentInput();
  Object.defineProperty(hiddenField, "authority", { value: true });
  assert.throws(() => buildNativeIntent(hiddenField), /fields must be enumerable/);
});

test("intent snapshots data descriptors without invoking accessors", () => {
  let getterReads = 0;
  const accessor = intentInput();
  Object.defineProperty(accessor, "action", {
    enumerable: true,
    get() {
      getterReads += 1;
      return getterReads === 1 ? "request_open_path" : "unregistered_effect";
    },
  });
  assert.throws(() => buildNativeIntent(accessor), /own data properties/);
  assert.equal(getterReads, 0);

  let propertyReads = 0;
  const lyingReads = new Proxy(intentInput(), {
    get(target, property, receiver) {
      propertyReads += 1;
      if (property === "action") {
        return "unregistered_effect";
      }
      return Reflect.get(target, property, receiver);
    },
  });
  assert.equal(buildNativeIntent(lyingReads).action, "request_open_path");
  assert.equal(propertyReads, 0);
});

test("unobserved outcome remains indeterminate", () => {
  const outcome = observeNativeOutcome({
    operationId: "operation:1",
    terminalObserved: false,
  });
  assert.deepEqual(outcome, {
    operationId: "operation:1",
    status: "indeterminate",
    outcomeDigest: null,
    effectAuthority: false,
  });
  assert.equal(Object.isFrozen(outcome), true);
});

test("terminalObserved is a strict boolean and nonterminal fields are exact", () => {
  for (const terminalObserved of [0, 1, null, undefined, "false"]) {
    assert.throws(
      () =>
        observeNativeOutcome({
          operationId: "operation:1",
          terminalObserved,
        }),
      /exactly true or false/,
    );
  }
  assert.throws(
    () =>
      observeNativeOutcome({
        operationId: "operation:1",
        terminalObserved: false,
        outcomeDigest: digest,
      }),
    /missing or unknown fields/,
  );
});

test("terminal claims fail closed without a trusted backend receipt", () => {
  for (const terminalStatus of ["succeeded", "failed"]) {
    assert.throws(
      () => observeNativeOutcome(terminalInput({ terminalStatus })),
      /trusted backend receipt/,
    );
  }
});

test("caller-supplied matching digests cannot authenticate a terminal claim", () => {
  const observerCredentialDigest = "ef".repeat(32);
  assert.throws(
    () =>
      observeNativeOutcome(
        terminalInput({ observerCredentialDigest }),
        observerCredentialDigest,
      ),
    /missing or unknown fields/,
  );
  assert.throws(
    () => observeNativeOutcome(terminalInput(), observerCredentialDigest),
    /trusted backend receipt/,
  );
});

test("terminal syntax is checked before the unavailable receipt boundary", () => {
  assert.throws(
    () => observeNativeOutcome(terminalInput({ terminalStatus: "unregistered" })),
    /terminalStatus is not registered/,
  );
  assert.throws(
    () => observeNativeOutcome(terminalInput({ outcomeDigest: "0".repeat(64) })),
    /non-zero/,
  );
});

test("terminal descriptor accessors are rejected without being invoked", () => {
  let getterReads = 0;
  const accessor = terminalInput();
  Object.defineProperty(accessor, "terminalStatus", {
    enumerable: true,
    get() {
      getterReads += 1;
      return getterReads === 1 ? "succeeded" : "unregistered";
    },
  });
  assert.throws(() => observeNativeOutcome(accessor), /own data properties/);
  assert.equal(getterReads, 0);
});

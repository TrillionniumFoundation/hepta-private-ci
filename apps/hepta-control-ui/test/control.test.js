import assert from "node:assert/strict";
import test from "node:test";

import {
  buildOperationIntent,
  buildLocalOperationProposalFromCanonicalJson,
  projectRuntime,
  projectRuntimeFromLocalCanonicalJson,
} from "../src/control.js";

const digest = "ab".repeat(32);
const runtimeSchema = "hepta.ui-control.local-runtime-observation.v1";
const operationSchema =
  "hepta.ui-control.local-operation-proposal-input.v1";

function canonicalJson(value) {
  const entries = Object.entries(value).sort(([left], [right]) =>
    left < right ? -1 : left > right ? 1 : 0,
  );
  return JSON.stringify(Object.fromEntries(entries));
}

test("runtime projection exposes only registered safe fields", () => {
  const projection = projectRuntime({
    moduleId: "runtime.agentd",
    status: "ready",
    revision: 7,
    digest,
    secret: "must-not-leak",
    providerPayload: { token: "must-not-leak" },
  });

  assert.deepEqual(projection, {
    moduleId: "runtime.agentd",
    status: "ready",
    revision: 7,
    digest,
    ready: true,
    authorityGranted: false,
    directStoreWrite: false,
  });
  assert.equal(Object.isFrozen(projection), true);
  assert.equal("secret" in projection, false);
  assert.equal("providerPayload" in projection, false);
});

test("operation intent cannot issue authority or write a store", () => {
  const intent = buildOperationIntent({
    operationId: "operation:1",
    subjectId: "module:1",
    action: "request_quarantine",
    expectedRevision: 3,
  });

  assert.equal(intent.authorityGranted, false);
  assert.equal(intent.directStoreWrite, false);
  assert.equal(intent.kind, "OperationIntentV1");
});

test("unknown actions fail closed", () => {
  assert.throws(
    () =>
      buildOperationIntent({
        operationId: "operation:1",
        subjectId: "module:1",
        action: "merge_and_release",
        expectedRevision: 3,
      }),
    /registered operator request/,
  );
});

test("invalid digest is rejected", () => {
  assert.throws(
    () =>
      projectRuntime({
        moduleId: "runtime.agentd",
        status: "ready",
        revision: 7,
        digest: "not-a-digest",
      }),
    /64 lowercase hexadecimal/,
  );
});

test("legacy V1 projection continues to ignore additional presentation data", () => {
  const projection = projectRuntime({
    moduleId: "runtime.agentd",
    status: "ready",
    revision: 7,
    digest,
    providerPayload: { token: "must-not-leak" },
  });
  assert.equal(projection.status, "ready");
  assert.equal("providerPayload" in projection, false);
});

test("canonical runtime projection rejects ambiguous encodings", () => {
  const encoded = canonicalJson({
    schema: runtimeSchema,
    moduleId: "runtime.agentd",
    status: "ready",
    revision: 7,
    digest,
  });
  const projection = projectRuntimeFromLocalCanonicalJson(encoded);
  assert.equal(projection.status, "ready");
  assert.equal(projection.ready, true);
  assert.equal(Object.isFrozen(projection), true);

  assert.throws(
    () => projectRuntimeFromLocalCanonicalJson(`${encoded} `),
    /canonical JSON form/,
  );
  assert.throws(
    () =>
      projectRuntimeFromLocalCanonicalJson(
        encoded.replace(
          '"status":"ready"',
          '"status":"degraded","status":"ready"',
        ),
      ),
    /canonical JSON form/,
  );
  assert.throws(
    () =>
      projectRuntimeFromLocalCanonicalJson(
        canonicalJson({
          schema: runtimeSchema,
          moduleId: "runtime.agentd",
          status: "ready",
          revision: 7,
          digest,
          authorityGranted: true,
        }),
      ),
    /missing, unknown, or unordered fields/,
  );
  assert.throws(
    () =>
      projectRuntimeFromLocalCanonicalJson(
        JSON.stringify({
          schema: runtimeSchema,
          status: "ready",
          moduleId: "runtime.agentd",
          revision: 7,
          digest,
        }),
      ),
    /missing, unknown, or unordered fields/,
  );
  assert.throws(
    () =>
      projectRuntimeFromLocalCanonicalJson(
        canonicalJson({
          schema: runtimeSchema,
          moduleId: "runtime.agentd",
          status: "ready",
          revision: 7,
          digest: "0".repeat(64),
        }),
      ),
    /non-zero/,
  );
});

test("canonical JSON ingress is byte bounded before object validation", () => {
  assert.throws(
    () => projectRuntimeFromLocalCanonicalJson(" ".repeat(4097)),
    /bounded canonical JSON/,
  );
  assert.throws(
    () => projectRuntimeFromLocalCanonicalJson(`"${"é".repeat(2048)}"`),
    /canonical JSON byte limit/,
  );
  assert.throws(
    () =>
      projectRuntimeFromLocalCanonicalJson({
        get status() {
          throw new Error("trap");
        },
      }),
    /bounded canonical JSON/,
  );
});

test("canonical operation input produces only a local authority-free proposal", () => {
  const encoded = canonicalJson({
    schema: operationSchema,
    operationId: "operation:1",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: Number.MAX_SAFE_INTEGER,
  });
  const proposal = buildLocalOperationProposalFromCanonicalJson(encoded);
  assert.deepEqual(proposal, {
    localSchema: "hepta.ui-control.local-operation-proposal.v1",
    operationId: "operation:1",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: Number.MAX_SAFE_INTEGER,
    authorityGranted: false,
    directStoreWrite: false,
  });
  assert.equal("kind" in proposal, false);
  assert.equal(Object.isFrozen(proposal), true);

  assert.throws(
    () =>
      buildLocalOperationProposalFromCanonicalJson(
        canonicalJson({
          schema: operationSchema,
          operationId: "x".repeat(129),
          subjectId: "runtime.agentd",
          action: "request_retry",
          expectedRevision: 1,
        }),
      ),
    /bounded stable identifier/,
  );
  assert.throws(
    () =>
      buildLocalOperationProposalFromCanonicalJson(
        canonicalJson({
          schema: operationSchema,
          operationId: "operation:1",
          subjectId: "runtime.agentd",
          action: "request_retry",
          expectedRevision: Number.MAX_SAFE_INTEGER + 1,
        }),
      ),
    /positive safe integer/,
  );
});

test("local schema versions and enum values fail closed", () => {
  assert.throws(
    () =>
      projectRuntimeFromLocalCanonicalJson(
        canonicalJson({
          schema: "hepta.ui-control.local-runtime-observation.v2",
          moduleId: "runtime.agentd",
          status: "ready",
          revision: 1,
          digest,
        }),
      ),
    /schema is unsupported/,
  );
  assert.throws(
    () =>
      projectRuntimeFromLocalCanonicalJson(
        canonicalJson({
          schema: runtimeSchema,
          moduleId: "runtime.agentd",
          status: "invented",
          revision: 1,
          digest,
        }),
      ),
    /registered runtime state/,
  );
  assert.throws(
    () =>
      buildLocalOperationProposalFromCanonicalJson(
        canonicalJson({
          schema: "hepta.ui-control.local-operation-proposal-input.v2",
          operationId: "operation:1",
          subjectId: "runtime.agentd",
          action: "request_retry",
          expectedRevision: 1,
        }),
      ),
    /schema is unsupported/,
  );
  assert.throws(
    () =>
      buildLocalOperationProposalFromCanonicalJson(
        canonicalJson({
          schema: operationSchema,
          operationId: "operation:1",
          subjectId: "runtime.agentd",
          action: "release",
          expectedRevision: 1,
        }),
      ),
    /registered operator request/,
  );
});

test("both local entrypoints enforce closed fields and canonical encoding", () => {
  const runtime = {
    schema: runtimeSchema,
    moduleId: "runtime.agentd",
    status: "ready",
    revision: 1,
    digest,
  };
  const operation = {
    schema: operationSchema,
    operationId: "operation:1",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: 1,
  };
  for (const [call, value, missing] of [
    [projectRuntimeFromLocalCanonicalJson, runtime, "digest"],
    [buildLocalOperationProposalFromCanonicalJson, operation, "action"],
  ]) {
    const absent = { ...value };
    delete absent[missing];
    assert.throws(() => call(canonicalJson(absent)), /missing, unknown/);
    assert.throws(
      () => call(canonicalJson({ ...value, unknown: true })),
      /missing, unknown/,
    );
    assert.throws(
      () => call(` ${canonicalJson(value)}`),
      /canonical JSON form/,
    );
    assert.throws(
      () => call(canonicalJson(value).replace('"schema"', '"\\u0073chema"')),
      /canonical JSON form/,
    );
  }
});

test("local entrypoints reject hostile proxies without invoking traps", () => {
  for (const call of [
    projectRuntimeFromLocalCanonicalJson,
    buildLocalOperationProposalFromCanonicalJson,
  ]) {
    let traps = 0;
    const hostile = new Proxy(
      {},
      {
        get() {
          traps += 1;
          throw new Error("unexpected get");
        },
        ownKeys() {
          traps += 1;
          throw new Error("unexpected ownKeys");
        },
      },
    );
    assert.throws(() => call(hostile), /bounded canonical JSON/);
    assert.equal(traps, 0);
  }
});

test("local input byte and identity boundaries are exact", () => {
  const exactBytes = `"${"é".repeat(2047)}"`;
  assert.equal(Buffer.byteLength(exactBytes), 4096);
  assert.throws(
    () => projectRuntimeFromLocalCanonicalJson(exactBytes),
    /must be an object/,
  );
  assert.throws(
    () => projectRuntimeFromLocalCanonicalJson(`${exactBytes}a`),
    /canonical JSON byte limit/,
  );

  const operation = {
    schema: operationSchema,
    operationId: "x".repeat(128),
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: 1,
  };
  assert.equal(
    buildLocalOperationProposalFromCanonicalJson(canonicalJson(operation))
      .operationId.length,
    128,
  );
  assert.throws(
    () =>
      buildLocalOperationProposalFromCanonicalJson(
        canonicalJson({ ...operation, operationId: "x".repeat(129) }),
      ),
    /bounded stable identifier/,
  );
  assert.throws(
    () =>
      buildLocalOperationProposalFromCanonicalJson(
        canonicalJson({ ...operation, expectedRevision: 0 }),
      ),
    /positive safe integer/,
  );
});

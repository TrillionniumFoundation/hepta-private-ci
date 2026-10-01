import assert from "node:assert/strict";
import test from "node:test";

import {
  WorkerFrameDecoder,
  MAX_BROWSER_WORKER_FRAME_BYTES,
  buildWorkerFrame,
  canonicalWorkerJson,
  encodeWorkerFrame,
} from "../src/worker-protocol.js";

function frame(overrides = {}) {
  return buildWorkerFrame({
    sessionId: "session.1",
    generation: 7,
    sequence: 1,
    kind: "dispatch",
    requestId: "operation.1",
    payload: { z: 2, a: { y: 4, x: 3 } },
    ...overrides,
  });
}

test("worker frames are canonical, digest-bound, and decode across chunk boundaries", () => {
  const encoded = encodeWorkerFrame(frame());
  const decoder = new WorkerFrameDecoder();
  assert.deepEqual(decoder.push(encoded.subarray(0, 3)), []);
  assert.deepEqual(decoder.push(encoded.subarray(3, 11)), []);
  const decoded = decoder.push(encoded.subarray(11));
  assert.equal(decoded.length, 1);
  assert.deepEqual(decoded[0].payload, { a: { x: 3, y: 4 }, z: 2 });
  decoder.end();
});

test("worker frames reject unknown fields and payload drift", () => {
  const valid = frame();
  assert.throws(
    () => encodeWorkerFrame({ ...valid, unexpected: true }),
    /missing or unknown fields/,
  );
  assert.throws(
    () => encodeWorkerFrame({ ...valid, payload: { a: 9 } }),
    /payload digest mismatch/,
  );
});

test("decoder rejects non-canonical and oversized announced frames", () => {
  const valid = frame();
  const nonCanonicalBody = Buffer.from(
    JSON.stringify({
      schema: valid.schema,
      protocolVersion: valid.protocolVersion,
      sessionId: valid.sessionId,
      generation: valid.generation,
      sequence: valid.sequence,
      kind: valid.kind,
      requestId: valid.requestId,
      payloadDigest: valid.payloadDigest,
      payload: valid.payload,
    }),
    "utf8",
  );
  assert.notEqual(
    nonCanonicalBody.toString("utf8"),
    canonicalWorkerJson(valid),
  );
  const prefix = Buffer.alloc(4);
  prefix.writeUInt32BE(nonCanonicalBody.length, 0);
  const decoder = new WorkerFrameDecoder();
  assert.throws(
    () => decoder.push(Buffer.concat([prefix, nonCanonicalBody])),
    /not canonical JSON/,
  );

  const invalidPrefix = Buffer.alloc(4);
  invalidPrefix.writeUInt32BE(1_048_577, 0);
  assert.throws(
    () => new WorkerFrameDecoder().push(invalidPrefix),
    /announced length is invalid/,
  );
});

test("decoder fails closed on partial channel termination", () => {
  const encoded = encodeWorkerFrame(frame());
  const decoder = new WorkerFrameDecoder();
  decoder.push(encoded.subarray(0, encoded.length - 1));
  assert.throws(() => decoder.end(), /partial frame/);
});

test("decoder rejects invalid UTF-8 even when lossy decoding preserves canonical JSON", () => {
  const encoded = encodeWorkerFrame(frame({ payload: { text: "�" } }));
  const replacementOffset = encoded.indexOf(Buffer.from("�", "utf8"));
  assert.notEqual(replacementOffset, -1);
  // A single invalid byte decodes to the same replacement character through
  // Buffer.toString(), hiding a wire mutation from canonical JSON comparison.
  const body = Buffer.concat([
    encoded.subarray(4, replacementOffset),
    Buffer.from([0xff]),
    encoded.subarray(replacementOffset + 3),
  ]);
  const prefix = Buffer.alloc(4);
  prefix.writeUInt32BE(body.length, 0);
  assert.throws(
    () => new WorkerFrameDecoder().push(Buffer.concat([prefix, body])),
    /not valid UTF-8/,
  );
});

test("worker serialization rejects Unicode and sparse arrays that Rust cannot canonicalize", () => {
  for (const payload of [{ text: "\ud800" }, { "\ud800": "value" }]) {
    assert.throws(() => frame({ payload }), /well-formed Unicode/);
  }
  assert.throws(
    () => frame({ payload: { items: new Array(1) } }),
    /plain object/,
  );
  assert.doesNotThrow(() =>
    encodeWorkerFrame(frame({ payload: { text: "😀�" } })),
  );
});

test("decoder rejects a leading UTF-8 BOM instead of stripping wire bytes", () => {
  const encoded = encodeWorkerFrame(frame());
  const body = Buffer.concat([
    Buffer.from([0xef, 0xbb, 0xbf]),
    encoded.subarray(4),
  ]);
  const prefix = Buffer.alloc(4);
  prefix.writeUInt32BE(body.length, 0);
  assert.throws(
    () => new WorkerFrameDecoder().push(Buffer.concat([prefix, body])),
    /not valid JSON/,
  );
});

test("a chunk containing arbitrarily many individually valid frames remains bounded", () => {
  const encoded = encodeWorkerFrame(frame());
  const count = Math.ceil(
    (MAX_BROWSER_WORKER_FRAME_BYTES + 5) / encoded.length,
  );
  const oversized = Buffer.concat(Array.from({ length: count }, () => encoded));
  assert.throws(
    () => new WorkerFrameDecoder().push(oversized),
    /chunk exceeds byte limit/,
  );
});

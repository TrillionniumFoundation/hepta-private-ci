import assert from "node:assert/strict";
import test from "node:test";
import { WorkerFrameDecoder, buildWorkerFrame, encodeWorkerFrame,
  MAX_BROWSER_WORKER_FRAME_BYTES } from "../src/worker-protocol.js";

function frame(payload = { value: "ok" }) {
  return encodeWorkerFrame(buildWorkerFrame({ sessionId: "profile", generation: 1,
    sequence: 1, kind: "response", requestId: "request", payload }));
}

test("worker decoder rejects malformed UTF-8 even when replacement matches the payload digest", () => {
  const valid = frame({ value: "\ufffd" });
  const index = valid.indexOf(Buffer.from("\ufffd"));
  assert.ok(index > 4);
  const invalid = Buffer.concat([valid.subarray(4, index), Buffer.from([0xff]), valid.subarray(index + 3)]);
  const length = Buffer.alloc(4);
  length.writeUInt32BE(invalid.length);
  assert.throws(() => new WorkerFrameDecoder().push(Buffer.concat([length, invalid])));
});

test("worker decoder rejects data after clean EOF", () => {
  const decoder = new WorkerFrameDecoder();
  decoder.end();
  assert.throws(() => decoder.push(frame()), /closed/);
});

test("worker decoder retains parse failure rather than resynchronizing on later bytes", () => {
  const decoder = new WorkerFrameDecoder();
  assert.throws(() => decoder.push(Buffer.from([0, 0, 0, 1, 123])), /valid JSON/);
  assert.throws(() => decoder.push(frame()), /valid JSON/);
});

test("worker decoder bounds total frames returned from one chunk", () => {
  assert.throws(() => new WorkerFrameDecoder().push(Buffer.concat(Array(65).fill(frame()))), /frame limit/);
});

test("worker decoder bounds input chunk before copying", () => {
  const chunk = Buffer.alloc(4 * (MAX_BROWSER_WORKER_FRAME_BYTES + 4) + 1);
  chunk.writeUInt32BE(MAX_BROWSER_WORKER_FRAME_BYTES);
  assert.throws(() => new WorkerFrameDecoder().push(chunk), /chunk exceeds/);
});

test("worker decoder copies arbitrarily fragmented valid input without changing bytes", () => {
  const decoder = new WorkerFrameDecoder();
  const wire = frame({ value: "x".repeat(4096) });
  const result = [];
  for (const byte of wire) result.push(...decoder.push(Buffer.from([byte])));
  decoder.end();
  assert.equal(result.length, 1);
  assert.deepEqual(encodeWorkerFrame(result[0]), wire);
});

test("worker decoder retains partial EOF failure", () => {
  const decoder = new WorkerFrameDecoder();
  decoder.push(frame().subarray(0, 8));
  assert.throws(() => decoder.end(), /partial frame/);
  assert.throws(() => decoder.push(frame()), /partial frame/);
});

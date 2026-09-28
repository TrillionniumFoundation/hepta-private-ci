import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import { decodeComputerActionFrameV1 } from "./computer-action-ir.js";
import { encodeComputerActionFrameV1, computerActionPayloadDigestV1 } from "./computer-action-ir.js";
const payload = { kind: "reference", referenceId: "native.ref.1" };
const frame = { operationId: "op.1", subjectId: "p.1", actuatorId: "native-shell",
  opcode: "notify_reference", targetRef: null, bodyGeneration: 1,
  sessionGeneration: 1, observationRevision: 1, deadlineMonotonicMicros: 100,
  preconditionDigest: "1".repeat(64), finalPayloadDigest: "2".repeat(64),
  expectedPostconditionDigest: "3".repeat(64), payload,
  argumentPayloadDigest: computerActionPayloadDigestV1("notify_reference", payload) };
for (const [name, offset] of [["body",12],["session",20],["observation",28],["deadline",36]]) {
  test(`checksummed zero ${name} is rejected`, () => {
    const bytes = encodeComputerActionFrameV1(frame);
    bytes.writeBigUInt64BE(0n, offset);
    createHash("sha256").update("hepta.computer-action.frame.v1")
      .update(bytes.subarray(0,-32)).digest().copy(bytes, bytes.length - 32);
    assert.throws(() => decodeComputerActionFrameV1(bytes), /positive/);
  });
}
test("decoder rejects non-byte and concurrently mutable input", () => {
  const bytes = encodeComputerActionFrameV1(frame);
  assert.throws(() => decodeComputerActionFrameV1(Array.from(bytes)), /byte/);
  const shared = new Uint8Array(new SharedArrayBuffer(bytes.length)); shared.set(bytes);
  assert.throws(() => decodeComputerActionFrameV1(shared), /shared/);
  assert.equal(decodeComputerActionFrameV1(new Uint8Array(bytes)).operationId, "op.1");
});

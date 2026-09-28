import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";

import {
  computerActionAuthorityBindingDigestV1,
  computerActionPayloadDigestV1,
  decodeComputerActionFrameV1,
  encodeComputerActionFrameV1,
} from "./computer-action-ir.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);

function frame(overrides = {}) {
  const payload = overrides.payload ?? { kind: "reference", referenceId: "path-ref-1" };
  const opcode = overrides.opcode ?? "open_path_reference";
  return {
    operationId: "operation-1",
    subjectId: "subject-1",
    actuatorId: "native-shell",
    opcode,
    targetRef: null,
    bodyGeneration: 5,
    sessionGeneration: 8,
    observationRevision: 13,
    deadlineMonotonicMicros: 21,
    preconditionDigest: D1,
    argumentPayloadDigest: computerActionPayloadDigestV1(opcode, payload),
    finalPayloadDigest: D2,
    expectedPostconditionDigest: D3,
    payload,
    ...overrides,
  };
}

const RUST_GOLDEN =
  "48414331000100060000000000000000000000050000000000000008000000000000000d0000000000000015000b6f7065726174696f6e2d3100097375626a6563742d31000c6e61746976652d7368656c6cac27cf5248407a85a0cfe7e4b899851d938c9b7d25e4039993332b1d769924dcb0ce1457f27c72529e170e766a645ecf041df62b3c7f6015b02063216029744d4e291d88e42d06d51721cbd10ce87fb65b5410fd880d493d2d974f4125b5fe2825bcb6e219f560fd3fb6419d9655353a0b17cffa60ecf00ed4715b2f9f5928680000000c000a706174682d7265662d310b86962fda869a8c716db9b07513eae16de01d804e38608bdc105558012484ac";

test("JavaScript codec consumes the frozen Rust frame and re-encodes byte-identically", () => {
  const bytes = Buffer.from(RUST_GOLDEN, "hex");
  const decoded = decodeComputerActionFrameV1(bytes);
  assert.equal(decoded.kind, "ComputerActionIRV1");
  assert.equal(decoded.opcode, "open_path_reference");
  assert.equal(
    decoded.finalPayloadDigest,
    createHash("sha256").update("final-payload").digest("hex"),
  );
  assert.deepEqual(encodeComputerActionFrameV1(decoded), bytes);
  assert.equal(
    computerActionAuthorityBindingDigestV1(decoded),
    bytes.subarray(bytes.length - 32).toString("hex"),
  );
});

test("authority binding changes with resolved final payload and target generation", () => {
  const original = frame();
  const digest = computerActionAuthorityBindingDigestV1(original);
  assert.notEqual(
    digest,
    computerActionAuthorityBindingDigestV1({ ...original, finalPayloadDigest: D3 }),
  );
  assert.notEqual(
    digest,
    computerActionAuthorityBindingDigestV1({ ...original, sessionGeneration: 9 }),
  );
});

test("unknown opcodes, payload drift and checksum drift fail closed", () => {
  const original = frame();
  assert.throws(
    () => encodeComputerActionFrameV1({ ...original, argumentPayloadDigest: D1 }),
    /does not bind/,
  );
  const bytes = encodeComputerActionFrameV1(original);
  const opcode = Buffer.from(bytes);
  opcode.writeUInt16BE(99, 6);
  assert.throws(() => decodeComputerActionFrameV1(opcode), /checksum mismatch/);
  const checksum = Buffer.from(bytes);
  checksum[checksum.length - 1] ^= 1;
  assert.throws(() => decodeComputerActionFrameV1(checksum), /checksum mismatch/);
});


test("portable integer limits reject authenticated-shaped unsafe u64 fields", () => {
  const original = frame({
    bodyGeneration: Number.MAX_SAFE_INTEGER,
    sessionGeneration: Number.MAX_SAFE_INTEGER,
    observationRevision: Number.MAX_SAFE_INTEGER,
    deadlineMonotonicMicros: Number.MAX_SAFE_INTEGER,
  });
  const bytes = encodeComputerActionFrameV1(original);
  assert.deepEqual(encodeComputerActionFrameV1(decodeComputerActionFrameV1(bytes)), bytes);
  for (const offset of [12, 20, 28, 36]) {
    const hostile = Buffer.from(bytes);
    hostile.writeBigUInt64BE(1n << 53n, offset);
    const body = hostile.subarray(0, hostile.length - 32);
    createHash("sha256").update("hepta.computer-action.frame.v1").update(body)
      .digest().copy(hostile, hostile.length - 32);
    assert.throws(() => decodeComputerActionFrameV1(hostile), /safe|range/);
  }
});

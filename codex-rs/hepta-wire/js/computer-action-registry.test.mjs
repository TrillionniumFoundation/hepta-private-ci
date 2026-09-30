import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import test from "node:test";
import {
  computerActionPayloadDigestV1,
  decodeComputerActionFrameV1,
  encodeComputerActionFrameV1,
} from "./computer-action-ir.js";

const root = new URL("../../../", import.meta.url);
const load = (path) => JSON.parse(readFileSync(new URL(path, root), "utf8"));
const protocol = load("docs/contracts/PROTOCOL_SCHEMAS.json").protocols.find(
  (row) => row.id === "ComputerActionIRV1",
);
const contract = load("docs/contracts/CONTRACTS.json").contracts.find(
  (row) => row.id === "ComputerActionIRV1",
);
const cases = [
  ["focus_target", "target.1", { kind: "none" }],
  ["activate_target", "target.1", { kind: "none" }],
  ["type_text_reference", "target.1", { kind: "reference", referenceId: "text.1" }],
  ["scroll", "target.1", { kind: "scroll", horizontalMilli: 1, verticalMilli: -1 }],
  ["navigate_reference", null, { kind: "reference", referenceId: "url.1" }],
  ["open_path_reference", null, { kind: "reference", referenceId: "path.1" }],
  ["reveal_path_reference", null, { kind: "reference", referenceId: "path.1" }],
  ["copy_text_reference", null, { kind: "reference", referenceId: "text.1" }],
  ["notify_reference", null, { kind: "reference", referenceId: "notice.1" }],
  ["wait_observation", null, { kind: "wait", waitMicros: 1 }],
  ["request_evidence", null, { kind: "none" }],
  ["stop", null, { kind: "none" }],
];

for (const [index, [opcode, targetRef, payload]] of cases.entries()) {
  test(`registered HAC1 code ${index + 1} consumes the published byte profile`, () => {
    assert.ok(protocol && contract, "protocol and contract are registered together");
    assert.equal(protocol.contractId, contract.id);
    assert.equal(contract.producer, "platform.wire");
    assert.ok(contract.consumers.includes("browser.servo"));
    if (index >= 5 && index <= 8) {
      assert.ok(contract.consumers.includes("ui.native"), "native reference consumer is registered");
    }
    assert.equal(contract.authorityDelta, "none");
    assert.equal(protocol.canonicalEncoding, "HAC1_big_endian_v1");
    const value = {
      operationId: "op.1", subjectId: "subject.1", actuatorId: "browser-servo",
      opcode, targetRef, bodyGeneration: 1, sessionGeneration: 1,
      observationRevision: 1, deadlineMonotonicMicros: 1000000,
      preconditionDigest: "1".repeat(64),
      argumentPayloadDigest: computerActionPayloadDigestV1(opcode, payload),
      finalPayloadDigest: "2".repeat(64), expectedPostconditionDigest: "3".repeat(64), payload,
    };
    const bytes = encodeComputerActionFrameV1(value);
    assert.ok(bytes.length <= protocol.maximumEncodedBytes);
    assert.equal(bytes.readUInt16BE(6), index + 1);
    const decoded = decodeComputerActionFrameV1(bytes);
    assert.equal(decoded.kind, protocol.id);
    assert.equal(decoded.authorityGranted, false);
    assert.deepEqual(decoded.payload, payload);
    assert.deepEqual(encodeComputerActionFrameV1(decoded), bytes);
    for (const [offset, invalid] of [[4, 2], [6, 13], [8, 2], [10, 1]]) {
      const hostile = Buffer.from(bytes);
      hostile.writeUInt16BE(invalid, offset);
      const body = hostile.subarray(0, hostile.length - 32);
      createHash("sha256").update("hepta.computer-action.frame.v1").update(body)
        .digest().copy(hostile, hostile.length - 32);
      assert.throws(() => decodeComputerActionFrameV1(hostile));
    }
  });
}

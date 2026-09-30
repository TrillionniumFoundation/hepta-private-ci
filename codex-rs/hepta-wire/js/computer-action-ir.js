import { createHash } from "node:crypto";

const MAGIC = Buffer.from("HAC1", "ascii");
export const COMPUTER_ACTION_FRAME_VERSION = 1;
const TARGET_FLAG = 1;
const KNOWN_FLAGS = TARGET_FLAG;
const FRAME_DOMAIN = Buffer.from("hepta.computer-action.frame.v1", "ascii");
const PAYLOAD_DOMAIN = Buffer.from("hepta.computer-action.payload.v1", "ascii");
export const MAX_COMPUTER_ACTION_FRAME_BYTES = 128 * 1024;
const MAX_REFERENCE_BYTES = 128;
const MAX_WAIT_MICROS = 60_000_000;
const MAX_SCROLL_MILLI = 100_000;
const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);

const OPCODES = new Map([
  [1, "focus_target"],
  [2, "activate_target"],
  [3, "type_text_reference"],
  [4, "scroll"],
  [5, "navigate_reference"],
  [6, "open_path_reference"],
  [7, "reveal_path_reference"],
  [8, "copy_text_reference"],
  [9, "notify_reference"],
  [10, "wait_observation"],
  [11, "request_evidence"],
  [12, "stop"],
]);
const OPCODE_CODES = new Map([...OPCODES].map(([code, name]) => [name, code]));
const TARGET_ACTIONS = new Set([
  "focus_target",
  "activate_target",
  "type_text_reference",
  "scroll",
]);
const NONE_ACTIONS = new Set([
  "focus_target",
  "activate_target",
  "request_evidence",
  "stop",
]);
const REFERENCE_ACTIONS = new Set([
  "type_text_reference",
  "navigate_reference",
  "open_path_reference",
  "reveal_path_reference",
  "copy_text_reference",
  "notify_reference",
]);

function fail(message) {
  throw new TypeError(message);
}

function stableId(value, name) {
  if (typeof value !== "string" || !STABLE_ID.test(value)) {
    fail(`${name} must be a bounded stable identifier`);
  }
  return value;
}

function digest(value, name) {
  if (typeof value !== "string" || !DIGEST.test(value) || value === ZERO_DIGEST) {
    fail(`${name} must be a non-zero lowercase SHA-256 digest`);
  }
  return value;
}

function positive(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) {
    fail(`${name} must be a positive safe integer`);
  }
  return value;
}

function boundedInteger(value, name, maximum) {
  if (!Number.isSafeInteger(value) || Math.abs(value) > maximum) {
    fail(`${name} must be a bounded safe integer`);
  }
  return value;
}

function sha256(...parts) {
  const hash = createHash("sha256");
  for (const part of parts) hash.update(part);
  return hash.digest();
}

function idBytes(value, name) {
  const accepted = stableId(value, name);
  const raw = Buffer.from(accepted, "utf8");
  if (raw.length < 1 || raw.length > MAX_REFERENCE_BYTES) {
    fail(`${name} exceeds the byte limit`);
  }
  const length = Buffer.alloc(2);
  length.writeUInt16BE(raw.length);
  return Buffer.concat([length, raw]);
}

function digestBytes(value, name) {
  return Buffer.from(digest(value, name), "hex");
}

function u64(value, name) {
  const accepted = positive(value, name);
  const bytes = Buffer.alloc(8);
  bytes.writeBigUInt64BE(BigInt(accepted));
  return bytes;
}

function encodePayload(opcode, payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    fail("payload must be an object");
  }
  if (NONE_ACTIONS.has(opcode)) {
    if (payload.kind !== "none" || Object.keys(payload).length !== 1) {
      fail("payload does not match opcode");
    }
    return Buffer.alloc(0);
  }
  if (REFERENCE_ACTIONS.has(opcode)) {
    if (
      payload.kind !== "reference" ||
      Object.keys(payload).length !== 2 ||
      !Object.hasOwn(payload, "referenceId")
    ) {
      fail("payload does not match opcode");
    }
    return idBytes(payload.referenceId, "payload.referenceId");
  }
  if (opcode === "scroll") {
    if (
      payload.kind !== "scroll" ||
      Object.keys(payload).length !== 3 ||
      !Object.hasOwn(payload, "horizontalMilli") ||
      !Object.hasOwn(payload, "verticalMilli")
    ) {
      fail("payload does not match opcode");
    }
    const horizontalMilli = boundedInteger(
      payload.horizontalMilli,
      "payload.horizontalMilli",
      MAX_SCROLL_MILLI,
    );
    const verticalMilli = boundedInteger(
      payload.verticalMilli,
      "payload.verticalMilli",
      MAX_SCROLL_MILLI,
    );
    if (horizontalMilli === 0 && verticalMilli === 0) {
      fail("scroll payload cannot be zero");
    }
    const bytes = Buffer.alloc(8);
    bytes.writeInt32BE(horizontalMilli, 0);
    bytes.writeInt32BE(verticalMilli, 4);
    return bytes;
  }
  if (opcode === "wait_observation") {
    if (
      payload.kind !== "wait" ||
      Object.keys(payload).length !== 2 ||
      !Object.hasOwn(payload, "waitMicros")
    ) {
      fail("payload does not match opcode");
    }
    const waitMicros = positive(payload.waitMicros, "payload.waitMicros");
    if (waitMicros > MAX_WAIT_MICROS) fail("payload.waitMicros exceeds the limit");
    return u64(waitMicros, "payload.waitMicros");
  }
  fail("opcode is not registered");
}

export function computerActionPayloadDigestV1(opcode, payload) {
  if (!OPCODE_CODES.has(opcode)) fail("opcode is not registered");
  return sha256(PAYLOAD_DOMAIN, encodePayload(opcode, payload)).toString("hex");
}

export function computerActionAuthorityBindingDigestV1(frame) {
  const encoded = encodeComputerActionFrameV1(frame);
  return encoded.subarray(encoded.length - 32).toString("hex");
}

export function encodeComputerActionFrameV1(frame) {
  if (!frame || typeof frame !== "object" || Array.isArray(frame)) {
    fail("frame must be an object");
  }
  const opcodeCode = OPCODE_CODES.get(frame.opcode);
  if (opcodeCode === undefined) fail("opcode is not registered");
  const hasTarget = frame.targetRef !== null && frame.targetRef !== undefined;
  if (TARGET_ACTIONS.has(frame.opcode) !== hasTarget) {
    fail("target presence does not match opcode");
  }
  const payload = encodePayload(frame.opcode, frame.payload);
  const payloadDigest = computerActionPayloadDigestV1(frame.opcode, frame.payload);
  if (digest(frame.argumentPayloadDigest, "argumentPayloadDigest") !== payloadDigest) {
    fail("argumentPayloadDigest does not bind the canonical payload");
  }
  digest(frame.finalPayloadDigest, "finalPayloadDigest");
  const header = Buffer.alloc(44);
  MAGIC.copy(header, 0);
  header.writeUInt16BE(COMPUTER_ACTION_FRAME_VERSION, 4);
  header.writeUInt16BE(opcodeCode, 6);
  header.writeUInt16BE(hasTarget ? TARGET_FLAG : 0, 8);
  header.writeUInt16BE(0, 10);
  header.writeBigUInt64BE(BigInt(positive(frame.bodyGeneration, "bodyGeneration")), 12);
  header.writeBigUInt64BE(BigInt(positive(frame.sessionGeneration, "sessionGeneration")), 20);
  header.writeBigUInt64BE(BigInt(positive(frame.observationRevision, "observationRevision")), 28);
  header.writeBigUInt64BE(
    BigInt(positive(frame.deadlineMonotonicMicros, "deadlineMonotonicMicros")),
    36,
  );
  const pieces = [
    header,
    idBytes(frame.operationId, "operationId"),
    idBytes(frame.subjectId, "subjectId"),
    idBytes(frame.actuatorId, "actuatorId"),
  ];
  if (hasTarget) pieces.push(idBytes(frame.targetRef, "targetRef"));
  pieces.push(
    digestBytes(frame.preconditionDigest, "preconditionDigest"),
    digestBytes(frame.argumentPayloadDigest, "argumentPayloadDigest"),
    digestBytes(frame.finalPayloadDigest, "finalPayloadDigest"),
    digestBytes(frame.expectedPostconditionDigest, "expectedPostconditionDigest"),
  );
  const payloadLength = Buffer.alloc(4);
  payloadLength.writeUInt32BE(payload.length);
  pieces.push(payloadLength, payload);
  const body = Buffer.concat(pieces);
  const encoded = Buffer.concat([body, sha256(FRAME_DOMAIN, body)]);
  if (encoded.length > MAX_COMPUTER_ACTION_FRAME_BYTES) fail("frame exceeds the byte limit");
  return encoded;
}

class Decoder {
  constructor(bytes) {
    this.bytes = bytes;
    this.offset = 0;
  }

  take(length) {
    if (!Number.isSafeInteger(length) || length < 0 || this.offset + length > this.bytes.length) {
      fail("frame is truncated");
    }
    const value = this.bytes.subarray(this.offset, this.offset + length);
    this.offset += length;
    return value;
  }

  u16() {
    const value = this.take(2).readUInt16BE();
    return value;
  }

  u32() {
    return this.take(4).readUInt32BE();
  }

  i32() {
    return this.take(4).readInt32BE();
  }

  u64(name) {
    const value = this.take(8).readBigUInt64BE();
    if (value > BigInt(Number.MAX_SAFE_INTEGER)) fail(`${name} exceeds the safe integer limit`);
    return positive(Number(value), name);
  }

  id(name) {
    const length = this.u16();
    if (length < 1 || length > MAX_REFERENCE_BYTES) fail(`${name} exceeds the byte limit`);
    return stableId(this.take(length).toString("utf8"), name);
  }

  digest(name) {
    return digest(this.take(32).toString("hex"), name);
  }

  done() {
    return this.offset === this.bytes.length;
  }
}

function decodePayload(opcode, bytes) {
  const decoder = new Decoder(bytes);
  if (NONE_ACTIONS.has(opcode)) {
    if (!decoder.done()) fail("payload does not match opcode");
    return Object.freeze({ kind: "none" });
  }
  if (REFERENCE_ACTIONS.has(opcode)) {
    const referenceId = decoder.id("payload.referenceId");
    if (!decoder.done()) fail("payload has trailing bytes");
    return Object.freeze({ kind: "reference", referenceId });
  }
  if (opcode === "scroll") {
    if (bytes.length !== 8) fail("payload does not match opcode");
    const horizontalMilli = boundedInteger(decoder.i32(), "payload.horizontalMilli", MAX_SCROLL_MILLI);
    const verticalMilli = boundedInteger(decoder.i32(), "payload.verticalMilli", MAX_SCROLL_MILLI);
    if (horizontalMilli === 0 && verticalMilli === 0) fail("scroll payload cannot be zero");
    return Object.freeze({ kind: "scroll", horizontalMilli, verticalMilli });
  }
  if (opcode === "wait_observation") {
    if (bytes.length !== 8) fail("payload does not match opcode");
    const waitMicros = decoder.u64("payload.waitMicros");
    if (waitMicros < 1 || waitMicros > MAX_WAIT_MICROS) fail("wait payload exceeds the limit");
    return Object.freeze({ kind: "wait", waitMicros });
  }
  fail("opcode is not registered");
}

export function decodeComputerActionFrameV1(value) {
  if (!(value instanceof Uint8Array)) fail("frame must be a byte array");
  if (value.buffer instanceof SharedArrayBuffer) fail("shared frame storage is forbidden");
  if (value.byteLength > MAX_COMPUTER_ACTION_FRAME_BYTES) fail("frame exceeds the byte limit");
  // Own the decoded bytes; no caller-owned buffer is retained past admission.
  const bytes = Buffer.from(value);
  if (bytes.length > MAX_COMPUTER_ACTION_FRAME_BYTES) fail("frame exceeds the byte limit");
  if (bytes.length < 32) fail("frame is truncated");
  const body = bytes.subarray(0, bytes.length - 32);
  const checksum = bytes.subarray(bytes.length - 32);
  if (!sha256(FRAME_DOMAIN, body).equals(checksum)) fail("frame checksum mismatch");
  const decoder = new Decoder(body);
  if (!decoder.take(4).equals(MAGIC)) fail("frame magic mismatch");
  const version = decoder.u16();
  if (version !== COMPUTER_ACTION_FRAME_VERSION) fail("frame version is not registered");
  const opcodeCode = decoder.u16();
  const opcode = OPCODES.get(opcodeCode);
  if (!opcode) fail("frame opcode is not registered");
  const flags = decoder.u16();
  if ((flags & ~KNOWN_FLAGS) !== 0) fail("frame contains unknown flags");
  if (decoder.u16() !== 0) fail("frame reserved bits are nonzero");
  const bodyGeneration = decoder.u64("bodyGeneration");
  const sessionGeneration = decoder.u64("sessionGeneration");
  const observationRevision = decoder.u64("observationRevision");
  const deadlineMonotonicMicros = decoder.u64("deadlineMonotonicMicros");
  const operationId = decoder.id("operationId");
  const subjectId = decoder.id("subjectId");
  const actuatorId = decoder.id("actuatorId");
  const targetRef = (flags & TARGET_FLAG) !== 0 ? decoder.id("targetRef") : null;
  if (TARGET_ACTIONS.has(opcode) !== (targetRef !== null)) {
    fail("target presence does not match opcode");
  }
  const preconditionDigest = decoder.digest("preconditionDigest");
  const argumentPayloadDigest = decoder.digest("argumentPayloadDigest");
  const finalPayloadDigest = decoder.digest("finalPayloadDigest");
  const expectedPostconditionDigest = decoder.digest("expectedPostconditionDigest");
  const payloadLength = decoder.u32();
  const payloadBytes = decoder.take(payloadLength);
  if (!decoder.done()) fail("frame has trailing bytes");
  const payload = decodePayload(opcode, payloadBytes);
  if (computerActionPayloadDigestV1(opcode, payload) !== argumentPayloadDigest) {
    fail("argumentPayloadDigest does not bind the canonical payload");
  }
  return Object.freeze({
    kind: "ComputerActionIRV1",
    operationId,
    subjectId,
    actuatorId,
    opcode,
    targetRef,
    bodyGeneration,
    sessionGeneration,
    observationRevision,
    deadlineMonotonicMicros,
    preconditionDigest,
    argumentPayloadDigest,
    finalPayloadDigest,
    expectedPostconditionDigest,
    payload,
    authorityGranted: false,
  });
}

import { createHash } from "node:crypto";

import {
  computerActionAuthorityBindingDigestV1,
  decodeComputerActionFrameV1,
} from "../../../codex-rs/hepta-wire/js/computer-action-ir.js";

const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);
const MAX_RESOURCE_BYTES = 65_536;
const MAX_REFERENCE_RESOLUTIONS = 16;
const PAYLOAD_DOMAIN = Buffer.from("hepta.native.platform-payload.v1\0", "utf8");
const OPCODE_ACTION = new Map([
  ["open_path_reference", "open_path"],
  ["reveal_path_reference", "reveal_path"],
  ["copy_text_reference", "copy_text"],
  ["notify_reference", "notify"],
]);

function record(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  const descriptors = Object.getOwnPropertyDescriptors(value);
  if (Reflect.ownKeys(descriptors).some((key) => typeof key !== "string" ||
      !Object.hasOwn(descriptors[key], "value") || !descriptors[key].enumerable)) {
    throw new TypeError(`${name} requires own data fields`);
  }
  return Object.freeze(Object.fromEntries(Object.entries(descriptors)
    .map(([key, field]) => [key, field.value])));
}

function stableId(value, name) {
  if (typeof value !== "string" || !STABLE_ID.test(value)) {
    throw new TypeError(`${name} must be a bounded stable identifier`);
  }
  return value;
}

function digest(value, name) {
  if (typeof value !== "string" || !DIGEST.test(value) || value === ZERO_DIGEST) {
    throw new TypeError(`${name} must be a non-zero lowercase SHA-256 digest`);
  }
  return value;
}

function positive(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

function boundedResource(value) {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.includes("\0") ||
    Buffer.byteLength(value, "utf8") > MAX_RESOURCE_BYTES
  ) {
    throw new TypeError("native resource must be bounded non-NUL UTF-8");
  }
  return stableId(value, "native resource reference");
}

function lengthPrefix(value) {
  const encoded = Buffer.from(value, "utf8");
  const length = Buffer.alloc(4);
  length.writeUInt32BE(encoded.length, 0);
  return [length, encoded];
}

export function nativePlatformPayloadDigestV1(action, resource) {
  if (![...OPCODE_ACTION.values()].includes(action)) {
    throw new TypeError("native platform action is not registered");
  }
  const bounded = boundedResource(resource);
  const hash = createHash("sha256");
  hash.update(PAYLOAD_DOMAIN);
  for (const part of lengthPrefix(action)) hash.update(part);
  for (const part of lengthPrefix(bounded)) hash.update(part);
  return hash.digest("hex");
}

export class InlineNativeReferenceResolver {
  #entries = new Map();

  constructor(values) {
    if (!Array.isArray(values) || values.length > MAX_REFERENCE_RESOLUTIONS) {
      throw new TypeError("native referenceResolutions must be a bounded array");
    }
    for (const raw of values) {
      const value = record(raw, "native reference resolution");
      const keys = Object.keys(value).sort();
      if (
        keys.length !== 2 ||
        keys[0] !== "referenceId" ||
        keys[1] !== "resource"
      ) {
        throw new TypeError("native reference resolution contains missing or unknown fields");
      }
      const referenceId = stableId(value.referenceId, "referenceId");
      if (this.#entries.has(referenceId)) {
        throw new TypeError("native reference resolution identity is duplicated");
      }
      this.#entries.set(referenceId, boundedResource(value.resource));
    }
  }

  async resolve(request) {
    const value = record(request, "native reference request");
    stableId(value.operationId, "operationId");
    stableId(value.subjectId, "subjectId");
    const referenceId = stableId(value.referenceId, "referenceId");
    const resource = this.#entries.get(referenceId);
    if (resource === undefined) {
      throw new TypeError("native reference was not admitted by the owner");
    }
    return Object.freeze({ resource });
  }
}

export async function nativeOperationFromComputerActionV1({
  frameBytes,
  principalId,
  sessionGeneration,
  bodyGeneration,
  viewRevision,
  viewDigest,
  grantPayloadDigest,
  currentMonotonicMicros,
  resolver,
}) {
  const principal = stableId(principalId, "principalId");
  const acceptedSessionGeneration = positive(sessionGeneration, "sessionGeneration");
  const acceptedViewGeneration = positive(bodyGeneration, "bodyGeneration");
  const acceptedViewRevision = positive(viewRevision, "viewRevision");
  const acceptedViewDigest = digest(viewDigest, "viewDigest");
  const acceptedGrantPayloadDigest = digest(grantPayloadDigest, "grantPayloadDigest");
  const now = positive(currentMonotonicMicros, "currentMonotonicMicros");
  if (
    resolver === null ||
    typeof resolver !== "object" ||
    typeof resolver.resolve !== "function"
  ) {
    throw new TypeError("native binary reference resolver is unavailable");
  }
  const frame = decodeComputerActionFrameV1(frameBytes);
  if (frame.subjectId !== principal) {
    throw new TypeError("binary native subject mismatch");
  }
  if (frame.actuatorId !== "native-shell") {
    throw new TypeError("binary native actuator mismatch");
  }
  if (frame.sessionGeneration !== acceptedSessionGeneration) {
    throw new TypeError("binary native session generation mismatch");
  }
  if (frame.bodyGeneration !== acceptedViewGeneration) {
    throw new TypeError("binary native body generation mismatch");
  }
  if (frame.observationRevision !== acceptedViewRevision) {
    throw new TypeError("binary native observation revision mismatch");
  }
  if (frame.preconditionDigest !== acceptedViewDigest) {
    throw new TypeError("binary native precondition does not match the current view");
  }
  if (frame.deadlineMonotonicMicros <= now) {
    throw new TypeError("binary native deadline has expired");
  }
  const action = OPCODE_ACTION.get(frame.opcode);
  if (action === undefined || frame.targetRef !== null || frame.payload.kind !== "reference") {
    throw new TypeError("ComputerAction opcode is not supported by ui.native");
  }
  const resolved = record(
    await resolver.resolve({
      kind: "reference",
      referenceId: frame.payload.referenceId,
      action,
      operationId: frame.operationId,
      subjectId: frame.subjectId,
      observationRevision: frame.observationRevision,
    }),
    "native reference resolution",
  );
  if (Object.keys(resolved).length !== 1 || !Object.hasOwn(resolved, "resource")) {
    throw new TypeError("native resolution requires exactly one resource reference");
  }
  const resource = boundedResource(resolved.resource);
  const finalPayloadDigest = nativePlatformPayloadDigestV1(action, resource);
  if (finalPayloadDigest !== frame.finalPayloadDigest) {
    throw new TypeError("resolved native resource does not match finalPayloadDigest");
  }
  return Object.freeze({
    operationId: frame.operationId,
    action,
    resource,
    displayedRevision: acceptedViewRevision,
    finalPayloadDigest,
    grantPayloadDigest: acceptedGrantPayloadDigest,
    sourceActionDigest: computerActionAuthorityBindingDigestV1(frame),
    deadlineMonotonicMicros: frame.deadlineMonotonicMicros,
  });
}

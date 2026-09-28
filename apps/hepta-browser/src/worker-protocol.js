import { createHash } from "node:crypto";

export const BROWSER_WORKER_PROTOCOL_VERSION = 1;
export const MAX_BROWSER_WORKER_FRAME_BYTES = 1_048_576;

const SCHEMA = "hepta.browser.worker-frame.v1";
const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const KINDS = new Set(["start", "observe", "dispatch", "reconcile", "stop", "response", "event"]);

function requireRecord(value, name) {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    Object.getPrototypeOf(value) !== Object.prototype
  ) {
    throw new TypeError(`${name} must be a plain object`);
  }
  return value;
}

function stableId(value, name) {
  if (typeof value !== "string" || !STABLE_ID.test(value)) {
    throw new TypeError(`${name} must be a bounded stable identifier`);
  }
  return value;
}

function positiveInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

function canonicalValue(value, depth = 0) {
  if (depth > 32) throw new TypeError("worker frame nesting exceeds limit");
  if (value === null || typeof value === "boolean" || typeof value === "string") return value;
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) throw new TypeError("worker frame numbers must be safe integers");
    return value;
  }
  if (Array.isArray(value)) return value.map((item) => canonicalValue(item, depth + 1));
  const record = requireRecord(value, "worker frame value");
  return Object.fromEntries(
    Object.keys(record)
      .sort()
      .map((key) => [key, canonicalValue(record[key], depth + 1)]),
  );
}

export function canonicalWorkerJson(value) {
  return JSON.stringify(canonicalValue(value));
}

export function workerPayloadDigest(payload) {
  return createHash("sha256").update(canonicalWorkerJson(payload)).digest("hex");
}

export function buildWorkerFrame({
  sessionId,
  generation,
  sequence,
  kind,
  requestId,
  payload,
}) {
  stableId(sessionId, "sessionId");
  positiveInteger(generation, "generation");
  positiveInteger(sequence, "sequence");
  if (!KINDS.has(kind)) throw new TypeError("worker frame kind is not registered");
  stableId(requestId, "requestId");
  const canonicalPayload = canonicalValue(requireRecord(payload, "payload"));
  return Object.freeze({
    schema: SCHEMA,
    protocolVersion: BROWSER_WORKER_PROTOCOL_VERSION,
    sessionId,
    generation,
    sequence,
    kind,
    requestId,
    payloadDigest: workerPayloadDigest(canonicalPayload),
    payload: canonicalPayload,
  });
}

export function normalizeWorkerFrame(value) {
  const frame = requireRecord(value, "worker frame");
  const keys = Object.keys(frame).sort();
  const expected = [
    "generation",
    "kind",
    "payload",
    "payloadDigest",
    "protocolVersion",
    "requestId",
    "schema",
    "sequence",
    "sessionId",
  ].sort();
  if (keys.length !== expected.length || keys.some((key, index) => key !== expected[index])) {
    throw new TypeError("worker frame contains missing or unknown fields");
  }
  if (frame.schema !== SCHEMA || frame.protocolVersion !== BROWSER_WORKER_PROTOCOL_VERSION) {
    throw new TypeError("worker frame protocol is unsupported");
  }
  const normalized = buildWorkerFrame(frame);
  if (frame.payloadDigest !== normalized.payloadDigest) {
    throw new TypeError("worker frame payload digest mismatch");
  }
  return normalized;
}

export function encodeWorkerFrame(value) {
  const normalized = normalizeWorkerFrame(value);
  const body = Buffer.from(canonicalWorkerJson(normalized), "utf8");
  if (body.length === 0 || body.length > MAX_BROWSER_WORKER_FRAME_BYTES) {
    throw new TypeError("worker frame exceeds byte limit");
  }
  const prefix = Buffer.allocUnsafe(4);
  prefix.writeUInt32BE(body.length, 0);
  return Buffer.concat([prefix, body]);
}

export class WorkerFrameDecoder {
  #header = Buffer.alloc(4);
  #headerUsed = 0;
  #body = null;
  #bodyUsed = 0;
  #failed = null;
  #ended = false;

  push(chunk) {
    if (this.#failed) throw this.#failed;
    if (this.#ended) throw new TypeError("worker decoder is closed");
    try {
      if (!(chunk instanceof Uint8Array)) {
        throw new TypeError("worker frame chunk must be bytes");
      }
      // Bound work and returned frames per call, not just an unfinished tail.
      // Native pipe chunks are much smaller; arbitrary callers must split input.
      if (chunk.byteLength > 4 * (MAX_BROWSER_WORKER_FRAME_BYTES + 4)) {
        throw new TypeError("worker input chunk exceeds byte limit");
      }
      const bytes = Buffer.from(chunk.buffer, chunk.byteOffset, chunk.byteLength);
      const frames = [];
      let offset = 0;
      while (offset < bytes.length) {
        if (this.#body === null) {
          const count = Math.min(4 - this.#headerUsed, bytes.length - offset);
          bytes.copy(this.#header, this.#headerUsed, offset, offset + count);
          this.#headerUsed += count;
          offset += count;
          if (this.#headerUsed !== 4) continue;
          const length = this.#header.readUInt32BE(0);
          if (length === 0 || length > MAX_BROWSER_WORKER_FRAME_BYTES) {
            throw new TypeError("worker frame announced length is invalid");
          }
          this.#body = Buffer.allocUnsafe(length);
          this.#bodyUsed = 0;
        }
        const count = Math.min(this.#body.length - this.#bodyUsed, bytes.length - offset);
        bytes.copy(this.#body, this.#bodyUsed, offset, offset + count);
        this.#bodyUsed += count;
        offset += count;
        if (this.#bodyUsed !== this.#body.length) continue;
        // Fatal decoding rejects invalid UTF-8 rather than replacing bytes in
        // an input whose canonical representation is part of its identity.
        const body = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(this.#body);
        let parsed;
        try {
          parsed = JSON.parse(body);
        } catch {
          throw new TypeError("worker frame body is not valid JSON");
        }
        const normalized = normalizeWorkerFrame(parsed);
        if (canonicalWorkerJson(normalized) !== body) {
          throw new TypeError("worker frame body is not canonical JSON");
        }
        if (frames.length >= 64) {
          throw new TypeError("worker input batch exceeds frame limit");
        }
        frames.push(normalized);
        this.#headerUsed = 0;
        this.#body = null;
        this.#bodyUsed = 0;
      }
      return frames;
    } catch (error) {
      this.#failed = error;
      this.#body = null;
      this.#bodyUsed = 0;
      this.#headerUsed = 0;
      throw error;
    }
  }

  end() {
    if (this.#failed) throw this.#failed;
    if (this.#headerUsed !== 0 || this.#body !== null) {
      this.#failed = new TypeError("worker channel ended with a partial frame");
      this.#body = null;
      throw this.#failed;
    }
    this.#ended = true;
  }
}

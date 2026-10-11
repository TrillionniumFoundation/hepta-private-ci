import { createHash } from "node:crypto";

export const BROWSER_AGENTD_PROTOCOL_VERSION = 1;
export const MAX_BROWSER_AGENTD_FRAME_BYTES = 1_048_576;

const SCHEMA = "hepta.browser.agentd-stdio-frame.v1";
const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const KINDS = new Set([
  "request",
  "response",
  "authority_challenge",
  "authority_enter",
  "dispatch_boundary",
]);

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
  if (depth > 32) throw new TypeError("Agentd browser frame nesting exceeds limit");
  if (value === null || typeof value === "boolean" || typeof value === "string") return value;
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) {
      throw new TypeError("Agentd browser frame numbers must be safe integers");
    }
    return value;
  }
  if (Array.isArray(value)) return value.map((item) => canonicalValue(item, depth + 1));
  const record = requireRecord(value, "Agentd browser frame value");
  return Object.fromEntries(
    Object.keys(record)
      .sort()
      .map((key) => [key, canonicalValue(record[key], depth + 1)]),
  );
}

export function canonicalAgentdBrowserJson(value) {
  return JSON.stringify(canonicalValue(value));
}

export function agentdBrowserPayloadDigest(payload) {
  return createHash("sha256").update(canonicalAgentdBrowserJson(payload)).digest("hex");
}

export function buildAgentdBrowserFrame({ sequence, kind, requestId, payload }) {
  positiveInteger(sequence, "sequence");
  if (!KINDS.has(kind)) throw new TypeError("Agentd browser frame kind is not registered");
  stableId(requestId, "requestId");
  const canonicalPayload = canonicalValue(requireRecord(payload, "payload"));
  return Object.freeze({
    schema: SCHEMA,
    protocolVersion: BROWSER_AGENTD_PROTOCOL_VERSION,
    sequence,
    kind,
    requestId,
    payloadDigest: agentdBrowserPayloadDigest(canonicalPayload),
    payload: canonicalPayload,
  });
}

export function normalizeAgentdBrowserFrame(value) {
  const frame = requireRecord(value, "Agentd browser frame");
  const keys = Object.keys(frame).sort();
  const expected = [
    "kind",
    "payload",
    "payloadDigest",
    "protocolVersion",
    "requestId",
    "schema",
    "sequence",
  ].sort();
  if (keys.length !== expected.length || keys.some((key, index) => key !== expected[index])) {
    throw new TypeError("Agentd browser frame contains missing or unknown fields");
  }
  if (frame.schema !== SCHEMA || frame.protocolVersion !== BROWSER_AGENTD_PROTOCOL_VERSION) {
    throw new TypeError("Agentd browser frame protocol is unsupported");
  }
  const normalized = buildAgentdBrowserFrame(frame);
  if (frame.payloadDigest !== normalized.payloadDigest) {
    throw new TypeError("Agentd browser frame payload digest mismatch");
  }
  return normalized;
}

export function encodeAgentdBrowserFrame(value) {
  const normalized = normalizeAgentdBrowserFrame(value);
  const body = Buffer.from(canonicalAgentdBrowserJson(normalized), "utf8");
  if (body.length === 0 || body.length > MAX_BROWSER_AGENTD_FRAME_BYTES) {
    throw new TypeError("Agentd browser frame exceeds byte limit");
  }
  const prefix = Buffer.allocUnsafe(4);
  prefix.writeUInt32BE(body.length, 0);
  return Buffer.concat([prefix, body]);
}

export class AgentdBrowserFrameDecoder {
  #buffer = Buffer.alloc(0);

  push(chunk) {
    if (!(chunk instanceof Uint8Array)) {
      throw new TypeError("Agentd browser frame chunk must be bytes");
    }
    this.#buffer = Buffer.concat([this.#buffer, Buffer.from(chunk)]);
    const frames = [];
    while (this.#buffer.length >= 4) {
      const length = this.#buffer.readUInt32BE(0);
      if (length === 0 || length > MAX_BROWSER_AGENTD_FRAME_BYTES) {
        throw new TypeError("Agentd browser frame announced length is invalid");
      }
      if (this.#buffer.length < 4 + length) break;
      const body = this.#buffer.subarray(4, 4 + length).toString("utf8");
      this.#buffer = this.#buffer.subarray(4 + length);
      let parsed;
      try {
        parsed = JSON.parse(body);
      } catch {
        throw new TypeError("Agentd browser frame body is not valid JSON");
      }
      const normalized = normalizeAgentdBrowserFrame(parsed);
      if (canonicalAgentdBrowserJson(normalized) !== body) {
        throw new TypeError("Agentd browser frame body is not canonical JSON");
      }
      frames.push(normalized);
    }
    if (this.#buffer.length > MAX_BROWSER_AGENTD_FRAME_BYTES + 4) {
      throw new TypeError("Agentd browser frame buffer exceeds limit");
    }
    return frames;
  }

  end() {
    if (this.#buffer.length !== 0) {
      throw new TypeError("Agentd browser channel ended with a partial frame");
    }
  }
}

import {
  createHash,
  createPublicKey,
  verify as verifySignature,
} from "node:crypto";
import { constants } from "node:fs";
import { lstat, open, realpath } from "node:fs/promises";
import { isAbsolute, join, resolve } from "node:path";

const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const SIGNATURE = /^[0-9a-f]{128}$/;
const MAX_RECEIPT_BYTES = 65_536;
const ED25519_SPKI_PREFIX = Buffer.from("302a300506032b6570032100", "hex");
const SIGNING_DOMAIN = Buffer.from(
  "hepta.browser.persisted-effect-observation.v2\0",
  "utf8",
);

function stableId(value, name) {
  if (typeof value !== "string" || !STABLE_ID.test(value)) {
    throw new TypeError(`${name} must be a bounded stable identifier`);
  }
  return value;
}

function digest(value, name) {
  if (typeof value !== "string" || !DIGEST.test(value) || /^0+$/.test(value)) {
    throw new TypeError(`${name} must be a non-zero lowercase SHA-256 digest`);
  }
  return value;
}

function positiveInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

function nonNegativeInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new TypeError(`${name} must be a non-negative safe integer`);
  }
  return value;
}

function exactKeys(value, keys, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (
    actual.length !== expected.length ||
    actual.some((key, index) => key !== expected[index])
  ) {
    throw new TypeError(`${name} contains missing or unknown fields`);
  }
}

function unsignedReceipt(receipt) {
  return {
    schema: receipt.schema,
    version: receipt.version,
    observerId: receipt.observerId,
    observerGeneration: receipt.observerGeneration,
    observedAtUnixMs: receipt.observedAtUnixMs,
    frontierDigest: receipt.frontierDigest,
    profileId: receipt.profileId,
    profileGeneration: receipt.profileGeneration,
    operationId: receipt.operationId,
    requestDigest: receipt.requestDigest,
    semanticDigest: receipt.semanticDigest,
    terminalObserved: receipt.terminalObserved,
    status: receipt.status,
    outcomeDigest: receipt.outcomeDigest,
  };
}

export function persistedEffectObservationSigningBytes(receipt) {
  return Buffer.concat([
    SIGNING_DOMAIN,
    Buffer.from(JSON.stringify(unsignedReceipt(receipt)), "utf8"),
  ]);
}

function rawEd25519PublicKey(value) {
  if (typeof value !== "string" || !DIGEST.test(value) || /^0+$/.test(value)) {
    throw new TypeError(
      "persisted reconciler verifyingKeyHex must be 32-byte lowercase hex",
    );
  }
  return createPublicKey({
    key: Buffer.concat([ED25519_SPKI_PREFIX, Buffer.from(value, "hex")]),
    format: "der",
    type: "spki",
  });
}

async function requirePrivateRoot(path) {
  const metadata = await lstat(path);
  if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
    throw new TypeError("persisted reconciler root must be a non-symlink directory");
  }
  if (process.platform !== "win32" && (metadata.mode & 0o077) !== 0) {
    throw new TypeError("persisted reconciler root permissions are too broad");
  }
  if ((await realpath(path)) !== resolve(path)) {
    throw new TypeError("persisted reconciler root contains a symlink");
  }
}

export class FilePersistedEffectReconciler {
  #root;
  #observerId;
  #verifyingKey;
  #minimumObserverGeneration;
  #minimumObservedAtUnixMs;
  #currentFrontierDigest;
  #now;
  #maxFutureSkewMs;

  constructor(
    root,
    {
      observerId,
      verifyingKeyHex,
      minimumObserverGeneration,
      minimumObservedAtUnixMs,
      currentFrontierDigest,
      now = () => Date.now(),
      maxFutureSkewMs = 60_000,
    },
  ) {
    if (typeof root !== "string" || !isAbsolute(root)) {
      throw new TypeError("persisted reconciler root must be absolute");
    }
    this.#root = resolve(root);
    this.#observerId = stableId(observerId, "persisted reconciler observerId");
    this.#verifyingKey = rawEd25519PublicKey(verifyingKeyHex);
    this.#minimumObserverGeneration = positiveInteger(
      minimumObserverGeneration,
      "persisted reconciler minimumObserverGeneration",
    );
    this.#minimumObservedAtUnixMs = positiveInteger(
      minimumObservedAtUnixMs,
      "persisted reconciler minimumObservedAtUnixMs",
    );
    this.#currentFrontierDigest = digest(
      currentFrontierDigest,
      "persisted reconciler currentFrontierDigest",
    );
    if (typeof now !== "function") {
      throw new TypeError("persisted reconciler now must be a function");
    }
    this.#now = now;
    this.#maxFutureSkewMs = nonNegativeInteger(
      maxFutureSkewMs,
      "persisted reconciler maxFutureSkewMs",
    );
  }

  async observe(input) {
    stableId(input.profileId, "profileId");
    const generation = positiveInteger(input.profileGeneration, "profileGeneration");
    const operationId = stableId(input.operationId, "operationId");
    const requestDigest = digest(input.requestDigest, "requestDigest");
    const semanticDigest = digest(input.semanticDigest, "semanticDigest");
    await requirePrivateRoot(this.#root);
    const path = join(
      this.#root,
      `${input.profileId}.${generation}.${operationId}.json`,
    );
    const noFollow = constants.O_NOFOLLOW ?? 0;
    let handle;
    try {
      handle = await open(path, constants.O_RDONLY | noFollow);
    } catch (error) {
      if (error?.code === "ENOENT") {
        return Object.freeze({
          operationId,
          requestDigest,
          semanticDigest,
          terminalObserved: false,
          observationReason: "authenticated_persisted_receipt_unavailable",
        });
      }
      throw error;
    }
    let body;
    try {
      const stat = await handle.stat();
      if (!stat.isFile() || stat.size < 2 || stat.size > MAX_RECEIPT_BYTES) {
        throw new TypeError("persisted reconciliation receipt is not a bounded regular file");
      }
      if (process.platform !== "win32" && (stat.mode & 0o077) !== 0) {
        throw new TypeError("persisted reconciliation receipt permissions are too broad");
      }
      body = await handle.readFile({ encoding: "utf8" });
    } finally {
      await handle.close();
    }

    let receipt;
    try {
      receipt = JSON.parse(body);
    } catch {
      throw new TypeError("persisted reconciliation receipt is malformed JSON");
    }
    exactKeys(
      receipt,
      [
        "schema",
        "version",
        "observerId",
        "observerGeneration",
        "observedAtUnixMs",
        "frontierDigest",
        "profileId",
        "profileGeneration",
        "operationId",
        "requestDigest",
        "semanticDigest",
        "terminalObserved",
        "status",
        "outcomeDigest",
        "signature",
      ],
      "persisted reconciliation receipt",
    );
    if (
      receipt.schema !== "hepta.browser.persisted-effect-observation.v2" ||
      receipt.version !== 2 ||
      receipt.terminalObserved !== true
    ) {
      throw new TypeError(
        "persisted reconciliation receipt is not a terminal signed v2 observation",
      );
    }
    if (
      stableId(receipt.observerId, "receipt.observerId") !== this.#observerId
    ) {
      throw new TypeError(
        "persisted reconciliation receipt observer is not the configured authority",
      );
    }
    const observerGeneration = positiveInteger(
      receipt.observerGeneration,
      "receipt.observerGeneration",
    );
    const observedAtUnixMs = positiveInteger(
      receipt.observedAtUnixMs,
      "receipt.observedAtUnixMs",
    );
    const frontierDigest = digest(
      receipt.frontierDigest,
      "receipt.frontierDigest",
    );
    if (observerGeneration < this.#minimumObserverGeneration) {
      throw new TypeError("persisted reconciliation receipt observer generation is stale");
    }
    if (observedAtUnixMs < this.#minimumObservedAtUnixMs) {
      throw new TypeError("persisted reconciliation receipt observation time is stale");
    }
    const nowUnixMs = positiveInteger(
      this.#now(),
      "persisted reconciliation current time",
    );
    if (
      nowUnixMs > Number.MAX_SAFE_INTEGER - this.#maxFutureSkewMs ||
      observedAtUnixMs > nowUnixMs + this.#maxFutureSkewMs
    ) {
      throw new TypeError("persisted reconciliation receipt observation time is in the future");
    }
    if (frontierDigest !== this.#currentFrontierDigest) {
      throw new TypeError("persisted reconciliation receipt frontier is stale");
    }
    if (
      stableId(receipt.profileId, "receipt.profileId") !== input.profileId ||
      positiveInteger(receipt.profileGeneration, "receipt.profileGeneration") !== generation ||
      stableId(receipt.operationId, "receipt.operationId") !== operationId ||
      digest(receipt.requestDigest, "receipt.requestDigest") !== requestDigest ||
      digest(receipt.semanticDigest, "receipt.semanticDigest") !== semanticDigest
    ) {
      throw new TypeError("persisted reconciliation receipt does not bind the durable operation");
    }
    if (receipt.status !== "succeeded" && receipt.status !== "failed") {
      throw new TypeError("persisted reconciliation receipt status is not registered");
    }
    const outcomeDigest = digest(receipt.outcomeDigest, "receipt.outcomeDigest");
    if (typeof receipt.signature !== "string" || !SIGNATURE.test(receipt.signature)) {
      throw new TypeError(
        "persisted reconciliation receipt signature must be lowercase Ed25519 hex",
      );
    }

    const signingBytes = persistedEffectObservationSigningBytes(receipt);
    const signature = Buffer.from(receipt.signature, "hex");
    if (!verifySignature(null, signingBytes, this.#verifyingKey, signature)) {
      throw new TypeError(
        "persisted reconciliation receipt signature is not authentic",
      );
    }
    const evidenceDigest = createHash("sha256")
      .update(signingBytes)
      .update(signature)
      .digest("hex");

    return Object.freeze({
      operationId,
      requestDigest,
      semanticDigest,
      terminalObserved: true,
      status: receipt.status,
      outcomeDigest,
      observerId: this.#observerId,
      observerGeneration,
      observedAtUnixMs,
      frontierDigest,
      evidenceDigest,
      observationReason: "authenticated_persisted_receipt",
    });
  }
}

export function createFilePersistedEffectReconciler(root, options) {
  const reconciler = new FilePersistedEffectReconciler(root, options);
  return (input) => reconciler.observe(input);
}

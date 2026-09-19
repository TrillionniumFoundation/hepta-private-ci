import { constants } from "node:fs";
import { lstat, open, realpath } from "node:fs/promises";
import { isAbsolute, join, resolve } from "node:path";

const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const MAX_RECEIPT_BYTES = 65_536;

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

  constructor(root) {
    if (typeof root !== "string" || !isAbsolute(root)) {
      throw new TypeError("persisted reconciler root must be absolute");
    }
    this.#root = resolve(root);
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
          observationReason: "trusted_persisted_receipt_unavailable",
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
        "profileId",
        "profileGeneration",
        "operationId",
        "requestDigest",
        "semanticDigest",
        "terminalObserved",
        "status",
        "outcomeDigest",
      ],
      "persisted reconciliation receipt",
    );
    if (
      receipt.schema !== "hepta.browser.persisted-effect-observation.v1" ||
      receipt.version !== 1 ||
      receipt.terminalObserved !== true
    ) {
      throw new TypeError("persisted reconciliation receipt is not a terminal v1 observation");
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
    return Object.freeze({
      operationId,
      requestDigest,
      semanticDigest,
      terminalObserved: true,
      status: receipt.status,
      outcomeDigest,
      observationReason: "trusted_persisted_receipt",
    });
  }
}

export function createFilePersistedEffectReconciler(root) {
  const reconciler = new FilePersistedEffectReconciler(root);
  return (input) => reconciler.observe(input);
}

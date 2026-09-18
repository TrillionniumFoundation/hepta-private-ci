import {
  ERROR_CODES,
  fail,
  nonNegativeInteger,
  positiveInteger,
  readOwnDataFields,
  requireDigest,
  requireRecord,
  stableId,
  utf8Bytes,
} from "./protocol.js";

export const PENDING_STORE_SCHEMA = "hepta.ui-control.pending-store.v1";
export const MAX_PERSISTED_PENDING = 1024;
export const MAX_PENDING_STORE_BYTES = 1024 * 1024;

const METHODS = new Set(["operation/request", "runtime/stop"]);
const STATUSES = new Set(["pending", "indeterminate"]);

function booleanOrNull(value, name) {
  if (value !== null && typeof value !== "boolean") {
    fail(ERROR_CODES.INVALID_INPUT, `${name} must be boolean or null`);
  }
  return value;
}

function requireBoolean(value, name) {
  if (typeof value !== "boolean") {
    fail(ERROR_CODES.INVALID_INPUT, `${name} must be boolean`);
  }
  return value;
}

export function normalizePendingRecord(value, name = "pending record") {
  const fields = readOwnDataFields(
    value,
    name,
    [
      "method",
      "operationId",
      "semanticDigest",
      "originSessionId",
      "originConnectionGeneration",
      "runtimeGeneration",
      "displayedRevision",
      "accepted",
      "status",
      "createdAtMs",
      "reconcileAttempts",
      "nextReconcileAtMs",
      "recoveryRequired",
    ],
  );
  const method = fields.method;
  if (!METHODS.has(method)) {
    fail(ERROR_CODES.INVALID_INPUT, `${name}.method is not registered`);
  }
  if (!STATUSES.has(fields.status)) {
    fail(ERROR_CODES.INVALID_INPUT, `${name}.status is not persistable`);
  }
  return Object.freeze({
    method,
    operationId: stableId(fields.operationId, `${name}.operationId`),
    semanticDigest: requireDigest(fields.semanticDigest, `${name}.semanticDigest`),
    originSessionId: stableId(fields.originSessionId, `${name}.originSessionId`),
    originConnectionGeneration: positiveInteger(
      fields.originConnectionGeneration,
      `${name}.originConnectionGeneration`,
    ),
    runtimeGeneration: positiveInteger(fields.runtimeGeneration, `${name}.runtimeGeneration`),
    displayedRevision: positiveInteger(fields.displayedRevision, `${name}.displayedRevision`),
    accepted: booleanOrNull(fields.accepted, `${name}.accepted`),
    status: fields.status,
    createdAtMs: nonNegativeInteger(fields.createdAtMs, `${name}.createdAtMs`),
    reconcileAttempts: nonNegativeInteger(
      fields.reconcileAttempts,
      `${name}.reconcileAttempts`,
    ),
    nextReconcileAtMs: nonNegativeInteger(
      fields.nextReconcileAtMs,
      `${name}.nextReconcileAtMs`,
    ),
    recoveryRequired: requireBoolean(fields.recoveryRequired, `${name}.recoveryRequired`),
  });
}

function normalizeRecords(records) {
  if (!Array.isArray(records) || records.length > MAX_PERSISTED_PENDING) {
    fail(ERROR_CODES.INVALID_INPUT, "pending store entries must be a bounded array");
  }
  const ids = new Set();
  const normalized = records.map((record, index) => {
    const value = normalizePendingRecord(record, `pending entries[${index}]`);
    if (ids.has(value.operationId)) {
      fail(ERROR_CODES.INVALID_INPUT, "pending store contains duplicate operation identity");
    }
    ids.add(value.operationId);
    return value;
  });
  return Object.freeze(normalized);
}

export class LocalStoragePendingStore {
  #storage;
  #key;

  constructor({ storage, key }) {
    if (
      storage === null ||
      typeof storage !== "object" ||
      typeof storage.getItem !== "function" ||
      typeof storage.setItem !== "function"
    ) {
      fail(ERROR_CODES.INVALID_INPUT, "storage must provide getItem/setItem");
    }
    if (typeof key !== "string" || key.length < 1 || key.length > 256) {
      fail(ERROR_CODES.INVALID_INPUT, "pending store key must be a bounded string");
    }
    this.#storage = storage;
    this.#key = key;
  }

  load() {
    let encoded;
    try {
      encoded = this.#storage.getItem(this.#key);
    } catch {
      fail(ERROR_CODES.PERSISTENCE_UNAVAILABLE, "pending operation storage is unavailable");
    }
    if (encoded == null || encoded === "") {
      return Object.freeze([]);
    }
    if (typeof encoded !== "string" || utf8Bytes(encoded) > MAX_PENDING_STORE_BYTES) {
      fail(ERROR_CODES.PERSISTENCE_UNAVAILABLE, "pending operation storage exceeds its byte bound");
    }
    let parsed;
    try {
      parsed = JSON.parse(encoded);
    } catch {
      fail(ERROR_CODES.PERSISTENCE_UNAVAILABLE, "pending operation storage is not valid JSON");
    }
    try {
      requireRecord(parsed, "pending store envelope");
      if (parsed.schema !== PENDING_STORE_SCHEMA) {
        fail(ERROR_CODES.INVALID_INPUT, "pending store schema is unsupported");
      }
      return normalizeRecords(parsed.entries);
    } catch (error) {
      if (error?.code === ERROR_CODES.PERSISTENCE_UNAVAILABLE) throw error;
      fail(ERROR_CODES.PERSISTENCE_UNAVAILABLE, "pending operation storage failed validation");
    }
  }

  save(records) {
    let normalized;
    try {
      normalized = normalizeRecords(records);
    } catch {
      fail(ERROR_CODES.PERSISTENCE_UNAVAILABLE, "pending operation state failed validation");
    }
    const encoded = JSON.stringify({ schema: PENDING_STORE_SCHEMA, entries: normalized });
    if (utf8Bytes(encoded) > MAX_PENDING_STORE_BYTES) {
      fail(ERROR_CODES.PERSISTENCE_UNAVAILABLE, "pending operation state exceeds storage bound");
    }
    try {
      this.#storage.setItem(this.#key, encoded);
    } catch {
      fail(ERROR_CODES.PERSISTENCE_UNAVAILABLE, "pending operation storage write failed");
    }
  }
}

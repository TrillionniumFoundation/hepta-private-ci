import { UI_CONTROL_ERROR_CODES as C, uiControlError } from "./errors.js";

const SCHEMA = "hepta.ui-control.scoped-recovery.v2";
const LEGACY_SCHEMA = "hepta.ui-control.recovery-state.v1";
const MAX_RECORD_BYTES = 8192;
const MAX_STORAGE_KEYS = 16384;
const LOCK_DEADLINE_MS = 5000;
const encoder = new TextEncoder();
const identityFields = [
  "protocolVersion",
  "method",
  "operationId",
  "semanticDigest",
  "action",
  "targetId",
  "reason",
  "sessionId",
  "connectionGeneration",
  "generation",
  "displayedRevision",
  "snapshotDigest",
];
const completionIdentityFields = [
  "operationId",
  "semanticDigest",
  "method",
  "action",
  "targetId",
  "generation",
  "displayedRevision",
];

function failure(message, cause) {
  return uiControlError(C.STORAGE, message, {
    retryable: true,
    details: { requestDispatched: false },
    cause,
  });
}

function identifier(value) {
  if (
    typeof value !== "string" ||
    !/^[A-Za-z0-9._:-]{1,128}$/u.test(value)
  ) {
    throw failure("Recovery identity is invalid.");
  }
  return value;
}

export class ScopedRecoveryStore {
  #storage;
  #locks;
  #prefix;
  #maxEntries;
  #scopeDigest;

  static async create({
    storage,
    locks,
    endpoint,
    identityId,
    protocolVersion,
    namespace = "default",
    maxEntries = 1024,
  }) {
    const url = new URL(endpoint);
    if (
      !["https:", "http:"].includes(url.protocol) ||
      url.username ||
      url.password ||
      url.search ||
      url.hash
    ) {
      throw failure(
        "Recovery endpoint must be an exact credential-free HTTP API base.",
      );
    }
    const binding = JSON.stringify([
      SCHEMA,
      url.href,
      identifier(namespace),
      identifier(identityId),
      identifier(protocolVersion),
    ]);
    const bytes = new Uint8Array(
      await globalThis.crypto.subtle.digest("SHA-256", encoder.encode(binding)),
    );
    const scopeDigest = [...bytes]
      .map(byte => byte.toString(16).padStart(2, "0"))
      .join("");
    return new ScopedRecoveryStore({
      storage,
      locks,
      scopeDigest,
      maxEntries,
    });
  }

  constructor({ storage, locks, scopeDigest, maxEntries }) {
    if (!storage || !locks || typeof locks.request !== "function") {
      throw failure(
        "Durable recovery storage and cross-tab locks are required for new mutations.",
      );
    }
    if (
      !Number.isSafeInteger(maxEntries) ||
      maxEntries < 1 ||
      maxEntries > 4096
    ) {
      throw failure("Recovery capacity is invalid.");
    }
    this.#storage = storage;
    this.#locks = locks;
    this.#maxEntries = maxEntries;
    this.#scopeDigest = scopeDigest;
    this.#prefix = `${SCHEMA}:${scopeDigest}:`;
  }

  #keys() {
    const count = this.#storage.length;
    if (
      !Number.isSafeInteger(count) ||
      count < 0 ||
      count > MAX_STORAGE_KEYS
    ) {
      throw failure(
        "Recovery storage key inventory exceeds its bounded budget.",
      );
    }
    const keys = [];
    for (let index = 0; index < count; index += 1) {
      const key = this.#storage.key(index);
      if (typeof key === "string" && key.startsWith(this.#prefix)) {
        keys.push(key);
      }
    }
    if (keys.length > this.#maxEntries) {
      throw failure("Recovery storage exceeds pending capacity.");
    }
    return keys.sort();
  }

  #decode(key, raw) {
    if (
      typeof raw !== "string" ||
      encoder.encode(raw).byteLength > MAX_RECORD_BYTES
    ) {
      throw failure("Recovery record exceeds its size bound.");
    }
    const value = JSON.parse(raw);
    if (
      value.schema !== SCHEMA ||
      value.scopeDigest !== this.#scopeDigest ||
      key !== this.#prefix + identifier(value.operation?.operationId)
    ) {
      throw failure("Recovery record does not match its authenticated scope.");
    }
    return value.operation;
  }

  async #withLock(signal, callback) {
    const deadline = new AbortController();
    const onAbort = () => deadline.abort(signal?.reason);
    if (signal?.aborted) onAbort();
    else signal?.addEventListener("abort", onAbort, { once: true });
    const timer = setTimeout(
      () => deadline.abort(new Error("recovery lock deadline")),
      LOCK_DEADLINE_MS,
    );
    try {
      return await this.#locks.request(
        this.#prefix,
        { mode: "exclusive", signal: deadline.signal },
        callback,
      );
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
    }
  }

  load() {
    try {
      const operations = [];
      for (const key of this.#keys()) {
        const raw = this.#storage.getItem(key);
        // Concurrent terminal cleanup may remove a key after enumeration.
        if (raw !== null) operations.push(this.#decode(key, raw));
      }
      return { schema: LEGACY_SCHEMA, operations };
    } catch (cause) {
      // Preserve corrupt data for diagnosis; never bulk-clear another tab.
      throw failure("Recovery state could not be loaded safely.", cause);
    }
  }

  async prepare(operation, { signal } = {}) {
    // The lock spans only durable admission, never network I/O. Different IDs
    // occupy different keys; one tab cannot overwrite another tab's ledger.
    try {
      return await this.#withLock(signal, () => {
        const key = this.#prefix + identifier(operation.operationId);
        const priorRaw = this.#storage.getItem(key);
        if (priorRaw !== null) {
          const prior = this.#decode(key, priorRaw);
          if (identityFields.some(field => prior[field] !== operation[field])) {
            throw uiControlError(
              C.OPERATION_CONFLICT,
              "Recovery identity has conflicting semantics.",
              { details: { requestDispatched: false } },
            );
          }
          // An existing record may already have crossed the network boundary.
          // Lookup, rather than dispatch, is mandatory even across tabs.
          throw uiControlError(
            C.AMBIGUOUS_SUBMISSION,
            "Operation was already reserved; recover it without resubmission.",
            {
              retryable: true,
              details: { requestDispatched: true },
            },
          );
        }
        if (this.#keys().length >= this.#maxEntries) {
          throw failure("Recovery capacity is exhausted.");
        }
        const raw = JSON.stringify({
          schema: SCHEMA,
          scopeDigest: this.#scopeDigest,
          operation,
        });
        if (encoder.encode(raw).byteLength > MAX_RECORD_BYTES) {
          throw failure("Recovery record exceeds its size bound.");
        }
        this.#storage.setItem(key, raw);
        if (this.#storage.getItem(key) !== raw) {
          throw failure("Recovery write could not be read back.");
        }
        return Object.freeze({
          discardRejected: async () => {
            try {
              await this.#withLock(undefined, () => {
                if (this.#storage.getItem(key) !== raw) return false;
                this.#storage.removeItem(key);
                if (this.#storage.getItem(key) !== null) {
                  throw failure(
                    "Rejected recovery record could not be removed atomically.",
                  );
                }
                return true;
              });
            } catch (cause) {
              throw failure(
                "Rejected recovery record could not be removed safely.",
                cause,
              );
            }
          },
        });
      });
    } catch (cause) {
      if (
        [C.OPERATION_CONFLICT, C.AMBIGUOUS_SUBMISSION].includes(cause?.code)
      ) {
        throw cause;
      }
      throw failure(
        "Recovery must be saved before dispatch; no new request was sent.",
        cause,
      );
    }
  }

  complete(operation, { signal } = {}) {
    // Only an independently queried terminal state or an authenticated
    // `found:false` non-admission disposition may remove its own record.
    if (operation.state !== "terminal") return Promise.resolve(false);
    const key = this.#prefix + identifier(operation.operationId);
    const work = this.#completeLocked(key, operation, signal);
    // Browser composition invokes cleanup opportunistically. Attach a handler
    // even when the caller does not await it, while preserving rejection for
    // callers that do await the returned promise.
    work.catch(error => {
      if (typeof globalThis.reportError === "function") {
        globalThis.reportError(error);
      }
    });
    return work;
  }

  async #completeLocked(key, operation, signal) {
    try {
      return await this.#withLock(signal, () => {
        const raw = this.#storage.getItem(key);
        if (raw === null) return false;
        const stored = this.#decode(key, raw);
        if (
          completionIdentityFields.some(
            field => stored[field] !== operation[field],
          )
        ) {
          throw failure(
            "Terminal recovery identity changed; the stored record was retained.",
          );
        }
        this.#storage.removeItem(key);
        if (this.#storage.getItem(key) !== null) {
          throw failure(
            "Terminal recovery record could not be removed atomically.",
          );
        }
        return true;
      });
    } catch (cause) {
      if (cause?.code === C.STORAGE) throw cause;
      throw failure("Terminal recovery record could not be removed.", cause);
    }
  }
}

import { UI_CONTROL_ERROR_CODES as C, uiControlError } from "./errors.js";
import {
  RECOVERY_DIRECTORY_SCHEMA,
  RecoveryDirectory,
  recoveryIdentifier,
  storageFailure,
} from "./recovery-directory.js";

const SCHEMA = "hepta.ui-control.scoped-recovery.v2";
const LEGACY_SCHEMA = "hepta.ui-control.recovery-state.v1";
const MAX_RECORD_BYTES = 8192;
const encoder = new TextEncoder();
const identityFields = Object.freeze([
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
]);
const completionIdentityFields = Object.freeze([
  "operationId",
  "semanticDigest",
  "method",
  "action",
  "targetId",
  "generation",
  "displayedRevision",
]);

function identityOf(operation) {
  return identityFields.map(field => operation[field]);
}

export class ScopedRecoveryStore {
  #scopeDigest;
  #prefix;
  #maxEntries;
  #directory;

  static async create({
    storage,
    locks,
    endpoint,
    identityId,
    protocolVersion,
    namespace = "default",
    maxEntries = 1024,
  }) {
    let url;
    try {
      url = new URL(endpoint);
    } catch (cause) {
      throw storageFailure(
        "Recovery endpoint must be an exact credential-free HTTP API base.",
        cause,
        "endpoint_invalid",
      );
    }
    if (
      !["https:", "http:"].includes(url.protocol) ||
      url.username ||
      url.password ||
      url.search ||
      url.hash
    ) {
      throw storageFailure(
        "Recovery endpoint must be an exact credential-free HTTP API base.",
        undefined,
        "endpoint_invalid",
      );
    }
    const binding = JSON.stringify([
      SCHEMA,
      url.href,
      recoveryIdentifier(namespace),
      recoveryIdentifier(identityId),
      recoveryIdentifier(protocolVersion),
    ]);
    const bytes = new Uint8Array(
      await globalThis.crypto.subtle.digest("SHA-256", encoder.encode(binding)),
    );
    const scopeDigest = [...bytes]
      .map(byte => byte.toString(16).padStart(2, "0"))
      .join("");
    const store = new ScopedRecoveryStore({
      storage,
      locks,
      scopeDigest,
      maxEntries,
    });
    await store.#directory.initialize();
    return store;
  }

  constructor({ storage, locks, scopeDigest, maxEntries }) {
    if (!storage || !locks || typeof locks.request !== "function") {
      throw storageFailure(
        "Durable recovery storage and cross-tab locks are required for new mutations.",
        undefined,
        "storage_or_lock_unavailable",
      );
    }
    if (
      !Number.isSafeInteger(maxEntries) ||
      maxEntries < 1 ||
      maxEntries > 4096
    ) {
      throw storageFailure(
        "Recovery capacity is invalid.",
        undefined,
        "capacity_invalid",
      );
    }
    this.#scopeDigest = scopeDigest;
    this.#maxEntries = maxEntries;
    this.#prefix = `${SCHEMA}:${scopeDigest}:`;
    this.#directory = new RecoveryDirectory({
      storage,
      locks,
      prefix: this.#prefix,
      key: `${RECOVERY_DIRECTORY_SCHEMA}:${scopeDigest}`,
      scopeDigest,
      maxEntries,
      recordKey: operationId => this.#recordKey(operationId),
      decodeRecord: (key, raw) => this.#decodeRecord(key, raw),
      identityFields,
    });
  }

  #recordKey(operationId) {
    return this.#prefix + recoveryIdentifier(operationId);
  }

  #decodeRecord(key, raw) {
    if (
      typeof raw !== "string" ||
      encoder.encode(raw).byteLength > MAX_RECORD_BYTES
    ) {
      throw storageFailure(
        "Recovery record exceeds its size bound.",
        undefined,
        "record_oversized",
      );
    }
    let value;
    try {
      value = JSON.parse(raw);
    } catch (cause) {
      throw storageFailure(
        "Recovery record is malformed.",
        cause,
        "record_corrupt",
      );
    }
    if (
      value === null ||
      typeof value !== "object" ||
      value.schema !== SCHEMA ||
      value.scopeDigest !== this.#scopeDigest ||
      key !== this.#recordKey(value.operation?.operationId)
    ) {
      throw storageFailure(
        "Recovery record does not match its authenticated scope.",
        undefined,
        "record_scope_mismatch",
      );
    }
    return value.operation;
  }

  load() {
    try {
      const operations = [];
      const entries = this.#directory.read();
      for (const [operationId, entry] of entries) {
        // An unlocked reader never adopts an in-progress local transition.
        if (entry.state !== "ready") continue;
        const key = this.#recordKey(operationId);
        const raw = this.#directory.readStorage(key, "record_read_failed");
        if (raw !== null) {
          operations.push(this.#decodeRecord(key, raw));
          continue;
        }

        // Terminal cleanup writes `removing` before deleting the record. Re-read
        // the exact directory entry so an unlocked load can distinguish that
        // legitimate race from a missing ready record. A still-ready identity
        // without its exact record is corruption and must disable mutation
        // rather than silently hiding a possibly dispatched operation.
        const current = this.#directory.read().get(operationId);
        if (current?.state === "ready") {
          throw storageFailure(
            "Recovery directory identity exists without its exact record.",
            undefined,
            "directory_record_missing",
          );
        }
      }
      return { schema: LEGACY_SCHEMA, operations };
    } catch (cause) {
      throw storageFailure(
        "Recovery state could not be loaded safely.",
        cause,
        cause?.details?.storageReason ?? "load_failed",
      );
    }
  }

  diagnostics() {
    try {
      return this.#directory.diagnostics();
    } catch (cause) {
      throw storageFailure(
        "Recovery diagnostics could not be read safely.",
        cause,
        cause?.details?.storageReason ?? "diagnostics_failed",
      );
    }
  }

  async prepare(operation, { signal } = {}) {
    try {
      return await this.#directory.withLock(signal, () => {
        const key = this.#recordKey(operation.operationId);
        const entries = this.#directory.read();
        if (this.#directory.reconcile(entries)) this.#directory.write(entries);
        const priorRaw = this.#directory.readStorage(key, "record_read_failed");
        if (priorRaw !== null) {
          const prior = this.#decodeRecord(key, priorRaw);
          if (identityFields.some(field => prior[field] !== operation[field])) {
            throw uiControlError(
              C.OPERATION_CONFLICT,
              "Recovery identity has conflicting semantics.",
              { details: { requestDispatched: false } },
            );
          }
          let repairFailure = null;
          if (!entries.has(operation.operationId)) {
            try {
              if (entries.size >= this.#maxEntries) {
                throw storageFailure(
                  "Recovery capacity is exhausted.",
                  undefined,
                  "capacity_exhausted",
                );
              }
              entries.set(
                operation.operationId,
                Object.freeze({ state: "ready" }),
              );
              this.#directory.write(entries);
            } catch (cause) {
              repairFailure = cause;
            }
          }
          throw uiControlError(
            C.AMBIGUOUS_SUBMISSION,
            repairFailure
              ? "Operation was already reserved; directory repair failed, so recover it without resubmission."
              : "Operation was already reserved; recover it without resubmission.",
            {
              retryable: true,
              details: {
                requestDispatched: true,
                ...(repairFailure
                  ? {
                    storageReason:
                      repairFailure?.details?.storageReason ??
                      "directory_repair_failed",
                  }
                  : {}),
              },
              cause: repairFailure ?? undefined,
            },
          );
        }
        if (entries.has(operation.operationId)) {
          throw storageFailure(
            "Recovery directory identity exists without its exact record.",
            undefined,
            "directory_record_missing",
          );
        }
        if (entries.size >= this.#maxEntries) {
          throw storageFailure(
            "Recovery capacity is exhausted.",
            undefined,
            "capacity_exhausted",
          );
        }
        const identity = Object.freeze(identityOf(operation));
        entries.set(
          operation.operationId,
          Object.freeze({ state: "reserving", identity }),
        );
        this.#directory.write(entries);
        const raw = JSON.stringify({
          schema: SCHEMA,
          scopeDigest: this.#scopeDigest,
          operation,
        });
        if (encoder.encode(raw).byteLength > MAX_RECORD_BYTES) {
          throw storageFailure(
            "Recovery record exceeds its size bound.",
            undefined,
            "record_oversized",
          );
        }
        this.#directory.writeStorage(key, raw, "record_write_failed");
        if (
          this.#directory.readStorage(
            key,
            "record_write_readback_failed",
          ) !== raw
        ) {
          throw storageFailure(
            "Recovery write could not be read back.",
            undefined,
            "record_write_readback_failed",
          );
        }
        entries.set(
          operation.operationId,
          Object.freeze({ state: "ready" }),
        );
        this.#directory.write(entries);
        return Object.freeze({
          discardRejected: async () => {
            try {
              await this.#directory.withLock(undefined, () => {
                const currentEntries = this.#directory.read();
                if (this.#directory.reconcile(currentEntries)) {
                  this.#directory.write(currentEntries);
                }
                if (
                  this.#directory.readStorage(key, "record_read_failed") !== raw
                ) {
                  return false;
                }
                currentEntries.set(
                  operation.operationId,
                  Object.freeze({ state: "removing", identity }),
                );
                this.#directory.write(currentEntries);
                this.#directory.removeStorage(key, "record_remove_failed");
                if (
                  this.#directory.readStorage(
                    key,
                    "record_remove_readback_failed",
                  ) !== null
                ) {
                  throw storageFailure(
                    "Rejected recovery record could not be removed atomically.",
                    undefined,
                    "record_remove_readback_failed",
                  );
                }
                currentEntries.delete(operation.operationId);
                this.#directory.write(currentEntries);
                return true;
              });
            } catch (cause) {
              throw storageFailure(
                "Rejected recovery record could not be removed safely.",
                cause,
                cause?.details?.storageReason ??
                  "rejected_record_cleanup_failed",
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
      throw storageFailure(
        "Recovery must be saved before dispatch; no new request was sent.",
        cause,
        cause?.details?.storageReason ?? "prepare_failed",
      );
    }
  }

  complete(operation, { signal } = {}) {
    if (operation.state !== "terminal") return Promise.resolve(false);
    const key = this.#recordKey(operation.operationId);
    const work = this.#completeLocked(key, operation, signal);
    work.catch(error => {
      if (typeof globalThis.reportError === "function") {
        globalThis.reportError(error);
      }
    });
    return work;
  }

  async #completeLocked(key, operation, signal) {
    try {
      return await this.#directory.withLock(signal, () => {
        const entries = this.#directory.read();
        if (this.#directory.reconcile(entries)) this.#directory.write(entries);
        const raw = this.#directory.readStorage(key, "record_read_failed");
        if (raw === null) {
          if (entries.has(operation.operationId)) {
            throw storageFailure(
              "Recovery directory identity exists without its exact record.",
              undefined,
              "directory_record_missing",
            );
          }
          return false;
        }
        const stored = this.#decodeRecord(key, raw);
        if (
          completionIdentityFields.some(
            field => stored[field] !== operation[field],
          )
        ) {
          throw storageFailure(
            "Terminal recovery identity changed; the stored record was retained.",
            undefined,
            "terminal_identity_mismatch",
          );
        }
        const indexed = entries.has(operation.operationId);
        if (indexed) {
          entries.set(
            operation.operationId,
            Object.freeze({
              state: "removing",
              identity: Object.freeze(identityOf(stored)),
            }),
          );
          this.#directory.write(entries);
        }
        this.#directory.removeStorage(key, "record_remove_failed");
        if (
          this.#directory.readStorage(
            key,
            "record_remove_readback_failed",
          ) !== null
        ) {
          throw storageFailure(
            "Terminal recovery record could not be removed atomically.",
            undefined,
            "record_remove_readback_failed",
          );
        }
        if (indexed) {
          entries.delete(operation.operationId);
          this.#directory.write(entries);
        }
        return true;
      });
    } catch (cause) {
      if (cause?.code === C.STORAGE) throw cause;
      throw storageFailure(
        "Terminal recovery record could not be removed.",
        cause,
        "terminal_cleanup_failed",
      );
    }
  }
}

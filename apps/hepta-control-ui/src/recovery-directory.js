import { UI_CONTROL_ERROR_CODES as C, uiControlError } from "./errors.js";

export const RECOVERY_DIRECTORY_SCHEMA =
  "hepta.ui-control.scoped-recovery-directory.v1";
const MAX_DIRECTORY_BYTES = 1024 * 1024;
const MAX_MIGRATION_KEYS = 16384;
const LOCK_DEADLINE_MS = 5000;
const encoder = new TextEncoder();
const states = new Set(["ready", "reserving", "removing"]);

export function storageFailure(message, cause, storageReason = "unknown") {
  return uiControlError(C.STORAGE, message, {
    retryable: true,
    details: { requestDispatched: false, storageReason },
    cause,
  });
}

export function recoveryIdentifier(value) {
  if (
    typeof value !== "string" ||
    !/^[A-Za-z0-9._:-]{1,128}$/u.test(value)
  ) {
    throw storageFailure(
      "Recovery identity is invalid.",
      undefined,
      "identity_invalid",
    );
  }
  return value;
}

export class RecoveryDirectory {
  #storage;
  #locks;
  #prefix;
  #key;
  #scopeDigest;
  #maxEntries;
  #recordKey;
  #decodeRecord;
  #identityFields;
  #migrationScans = 0;
  #migrationKeys = 0;

  constructor({
    storage,
    locks,
    prefix,
    key,
    scopeDigest,
    maxEntries,
    recordKey,
    decodeRecord,
    identityFields,
  }) {
    this.#storage = storage;
    this.#locks = locks;
    this.#prefix = prefix;
    this.#key = key;
    this.#scopeDigest = scopeDigest;
    this.#maxEntries = maxEntries;
    this.#recordKey = recordKey;
    this.#decodeRecord = decodeRecord;
    this.#identityFields = identityFields;
  }

  readStorage(key, storageReason) {
    try {
      return this.#storage.getItem(key);
    } catch (cause) {
      throw storageFailure(
        "Recovery storage could not be read.",
        cause,
        storageReason,
      );
    }
  }

  writeStorage(key, value, storageReason) {
    try {
      this.#storage.setItem(key, value);
    } catch (cause) {
      throw storageFailure(
        "Recovery storage could not be written.",
        cause,
        storageReason,
      );
    }
  }

  removeStorage(key, storageReason) {
    try {
      this.#storage.removeItem(key);
    } catch (cause) {
      throw storageFailure(
        "Recovery storage could not be removed.",
        cause,
        storageReason,
      );
    }
  }

  #decode(raw) {
    if (
      typeof raw !== "string" ||
      encoder.encode(raw).byteLength > MAX_DIRECTORY_BYTES
    ) {
      throw storageFailure(
        "Recovery directory exceeds its size bound.",
        undefined,
        "directory_oversized",
      );
    }
    let value;
    try {
      value = JSON.parse(raw);
    } catch (cause) {
      throw storageFailure(
        "Recovery directory is malformed.",
        cause,
        "directory_corrupt",
      );
    }
    const rootNames = value !== null &&
      typeof value === "object" &&
      !Array.isArray(value)
      ? Object.keys(value).sort()
      : [];
    if (
      rootNames.length !== 3 ||
      rootNames[0] !== "entries" ||
      rootNames[1] !== "schema" ||
      rootNames[2] !== "scopeDigest" ||
      value.schema !== RECOVERY_DIRECTORY_SCHEMA ||
      value.scopeDigest !== this.#scopeDigest ||
      !Array.isArray(value.entries)
    ) {
      throw storageFailure(
        "Recovery directory does not match its authenticated scope.",
        undefined,
        "directory_scope_mismatch",
      );
    }
    if (value.entries.length > this.#maxEntries) {
      throw storageFailure(
        "Recovery directory exceeds pending capacity.",
        undefined,
        "capacity_exhausted",
      );
    }
    const entries = new Map();
    let previous = null;
    for (const item of value.entries) {
      if (item === null || typeof item !== "object" || Array.isArray(item)) {
        throw storageFailure(
          "Recovery directory entry is invalid.",
          undefined,
          "directory_corrupt",
        );
      }
      const operationId = recoveryIdentifier(item.operationId);
      if (
        !states.has(item.state) ||
        (previous !== null && operationId <= previous)
      ) {
        throw storageFailure(
          "Recovery directory entry is invalid.",
          undefined,
          "directory_corrupt",
        );
      }
      const names = Object.keys(item).sort();
      const expected = item.state === "ready"
        ? ["operationId", "state"]
        : ["identity", "operationId", "state"];
      if (
        names.length !== expected.length ||
        names.some((name, index) => name !== expected[index]) ||
        (item.state !== "ready" &&
          (!Array.isArray(item.identity) ||
            item.identity.length !== this.#identityFields.length))
      ) {
        throw storageFailure(
          "Recovery directory entry is invalid.",
          undefined,
          "directory_corrupt",
        );
      }
      entries.set(
        operationId,
        item.state === "ready"
          ? Object.freeze({ state: "ready" })
          : Object.freeze({
            state: item.state,
            identity: Object.freeze([...item.identity]),
          }),
      );
      previous = operationId;
    }
    return entries;
  }

  #encode(entries) {
    if (!(entries instanceof Map) || entries.size > this.#maxEntries) {
      throw storageFailure(
        "Recovery directory exceeds pending capacity.",
        undefined,
        "capacity_exhausted",
      );
    }
    const ordered = [...entries].sort(([left], [right]) =>
      left < right ? -1 : left > right ? 1 : 0);
    const raw = JSON.stringify({
      schema: RECOVERY_DIRECTORY_SCHEMA,
      scopeDigest: this.#scopeDigest,
      entries: ordered.map(([operationId, entry]) => entry.state === "ready"
        ? { operationId, state: "ready" }
        : {
          operationId,
          state: entry.state,
          identity: [...entry.identity],
        }),
    });
    if (encoder.encode(raw).byteLength > MAX_DIRECTORY_BYTES) {
      throw storageFailure(
        "Recovery directory exceeds its size bound.",
        undefined,
        "directory_oversized",
      );
    }
    return raw;
  }

  read() {
    const raw = this.readStorage(this.#key, "directory_read_failed");
    if (raw === null) {
      throw storageFailure(
        "Recovery directory is missing after initialization.",
        undefined,
        "directory_missing",
      );
    }
    return this.#decode(raw);
  }

  write(entries) {
    const raw = this.#encode(entries);
    this.writeStorage(this.#key, raw, "directory_write_failed");
    if (this.readStorage(this.#key, "directory_readback_failed") !== raw) {
      throw storageFailure(
        "Recovery directory write could not be read back.",
        undefined,
        "directory_write_readback_failed",
      );
    }
  }

  #scanLegacyRecords() {
    let count;
    try {
      count = this.#storage.length;
    } catch (cause) {
      throw storageFailure(
        "Recovery storage inventory could not be read.",
        cause,
        "migration_inventory_read_failed",
      );
    }
    if (
      !Number.isSafeInteger(count) ||
      count < 0 ||
      count > MAX_MIGRATION_KEYS
    ) {
      throw storageFailure(
        "Recovery storage key inventory exceeds its bounded migration budget.",
        undefined,
        "migration_inventory_exceeded",
      );
    }
    this.#migrationScans += 1;
    this.#migrationKeys += count;
    const entries = new Map();
    for (let index = 0; index < count; index += 1) {
      let key;
      try {
        key = this.#storage.key(index);
      } catch (cause) {
        throw storageFailure(
          "Recovery storage inventory could not be enumerated.",
          cause,
          "migration_enumeration_failed",
        );
      }
      if (typeof key !== "string" || !key.startsWith(this.#prefix)) continue;
      const raw = this.readStorage(key, "record_read_failed");
      if (raw === null) continue;
      const operation = this.#decodeRecord(key, raw);
      entries.set(
        recoveryIdentifier(operation.operationId),
        Object.freeze({ state: "ready" }),
      );
      if (entries.size > this.#maxEntries) {
        throw storageFailure(
          "Recovery storage exceeds pending capacity.",
          undefined,
          "capacity_exhausted",
        );
      }
    }
    return entries;
  }

  #sameIdentity(identity, operation) {
    return Array.isArray(identity) &&
      identity.length === this.#identityFields.length &&
      this.#identityFields.every(
        (field, index) => identity[index] === operation[field],
      );
  }

  reconcile(entries) {
    let changed = false;
    for (const [operationId, entry] of [...entries]) {
      if (entry.state === "ready") continue;
      const key = this.#recordKey(operationId);
      const raw = this.readStorage(key, "record_read_failed");
      if (raw === null) {
        entries.delete(operationId);
        changed = true;
        continue;
      }
      const operation = this.#decodeRecord(key, raw);
      if (!this.#sameIdentity(entry.identity, operation)) {
        throw storageFailure(
          "Recovery directory transition changed identity; data was retained.",
          undefined,
          "directory_identity_mismatch",
        );
      }
      if (entry.state === "reserving") {
        this.removeStorage(key, "record_remove_failed");
        if (
          this.readStorage(key, "record_remove_readback_failed") !== null
        ) {
          throw storageFailure(
            "Interrupted recovery reservation could not be removed atomically.",
            undefined,
            "reservation_repair_failed",
          );
        }
        entries.delete(operationId);
      } else {
        entries.set(operationId, Object.freeze({ state: "ready" }));
      }
      changed = true;
    }
    return changed;
  }

  async initialize() {
    try {
      const observed = this.readStorage(this.#key, "directory_read_failed");
      if (observed !== null) {
        const entries = this.#decode(observed);
        if ([...entries.values()].every(entry => entry.state === "ready")) {
          return;
        }
      }
      await this.withLock(undefined, () => {
        const raw = this.readStorage(this.#key, "directory_read_failed");
        if (raw === null) {
          this.write(this.#scanLegacyRecords());
          return;
        }
        const entries = this.#decode(raw);
        if (this.reconcile(entries)) this.write(entries);
      });
    } catch (cause) {
      if (cause?.code === C.STORAGE) throw cause;
      throw storageFailure(
        "Recovery directory could not be initialized safely.",
        cause,
        "directory_initialization_failed",
      );
    }
  }

  async withLock(signal, callback) {
    const deadline = new AbortController();
    const onAbort = () => deadline.abort(signal?.reason);
    if (signal?.aborted) onAbort();
    else signal?.addEventListener("abort", onAbort, { once: true });
    const timer = setTimeout(
      () => deadline.abort(new Error("recovery lock deadline")),
      LOCK_DEADLINE_MS,
    );
    let entered = false;
    try {
      return await this.#locks.request(
        this.#prefix,
        { mode: "exclusive", signal: deadline.signal },
        () => {
          entered = true;
          return callback();
        },
      );
    } catch (cause) {
      if (entered) throw cause;
      throw storageFailure(
        "Recovery cross-tab lock could not be acquired.",
        cause,
        "lock_unavailable",
      );
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
    }
  }

  diagnostics() {
    const entries = this.read();
    const counts = { ready: 0, reserving: 0, removing: 0 };
    for (const entry of entries.values()) counts[entry.state] += 1;
    return Object.freeze({
      schema: RECOVERY_DIRECTORY_SCHEMA,
      entries: entries.size,
      maxEntries: this.#maxEntries,
      states: Object.freeze(counts),
      migrationScans: this.#migrationScans,
      migrationKeys: this.#migrationKeys,
    });
  }
}

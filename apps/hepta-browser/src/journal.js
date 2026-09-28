import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { lstat, mkdir, open, realpath } from "node:fs/promises";
import { dirname, isAbsolute, resolve } from "node:path";

const SCHEMA = "hepta.browser.operation-journal.v1";
const MAX_LINE_BYTES = 262_144;
const MAX_FILE_BYTES = 64 * 1024 * 1024;
const MAX_PENDING_OPERATIONS = 64;
const UTF8 = new TextEncoder();

function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

function canonical(value) {
  return JSON.stringify(value);
}

function checksum(value) {
  return createHash("sha256").update(canonical(value)).digest("hex");
}

function keyOf(record) {
  return `${record.profileId}\u0000${record.generation}\u0000${record.operationId}`;
}

function freezeRecord(record) {
  const snapshot = { ...record };
  // Older V1 persisted-reconciliation callers spread a public receipt into
  // the observation. Remove only these fixed, non-authorizing projections;
  // verify the original on-disk checksum before this normalization on replay.
  if (Object.hasOwn(snapshot, "kind")) {
    if (snapshot.kind !== "BrowserEffectObservationV1") throw new TypeError("unknown legacy journal projection");
    delete snapshot.kind;
  }
  for (const field of ["networkAuthority", "filesystemAuthority", "credentialExportAuthority"]) {
    if (Object.hasOwn(snapshot, field)) {
      if (snapshot[field] !== false) throw new TypeError("journal projection cannot grant authority");
      delete snapshot[field];
    }
  }
  return Object.freeze(snapshot);
}

// V1 stores scalar snapshots. Identity/authority metadata never changes when
// an outcome advances; matching a digest is not permission to rewrite fields.
const OUTCOME_KEYS = new Set(["status", "terminalObserved", "outcomeDigest", "observationReason"]);
const ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^(?!0{64}$)[0-9a-f]{64}$/;

function validateRecord(record) {
  requireRecord(record, "journal record");
  if (typeof record.profileId !== "string" || typeof record.operationId !== "string"
      || !ID.test(record.profileId) || !ID.test(record.operationId)
      || !Number.isSafeInteger(record.generation) || record.generation < 1
      || typeof record.requestDigest !== "string" || !DIGEST.test(record.requestDigest)
      || typeof record.semanticDigest !== "string" || !DIGEST.test(record.semanticDigest)) {
    throw new TypeError("browser journal record identity is invalid");
  }
  for (const value of Object.values(record)) {
    if (value !== null && !["string", "number", "boolean"].includes(typeof value)
        || typeof value === "number" && !Number.isFinite(value)) {
      throw new TypeError("browser journal record must be a finite scalar snapshot");
    }
  }
  if (typeof record.terminalObserved !== "boolean"
      || (record.terminalObserved
        ? !["succeeded", "failed"].includes(record.status)
          || typeof record.outcomeDigest !== "string" || !DIGEST.test(record.outcomeDigest)
        : record.status !== "indeterminate" || record.outcomeDigest !== null)) {
    throw new TypeError("browser journal terminal observation is inconsistent");
  }
  return record;
}

function sameFields(a, b, keys) {
  return keys.every((key) => Object.hasOwn(a, key) === Object.hasOwn(b, key) && a[key] === b[key]);
}

function advanceRecord(type, prior, record) {
  validateRecord(record);
  const keys = new Set([...Object.keys(record), ...Object.keys(prior ?? {})]);
  if (prior && !sameFields(prior, record, [...keys].filter((key) => !OUTCOME_KEYS.has(key)))) {
    throw new TypeError("journal operation changed immutable semantics");
  }
  if (type === "dispatch") {
    if (record.terminalObserved) throw new TypeError("dispatch cannot manufacture a terminal observation");
    // Retain the latest observed result, including after a replayed old dispatch.
    return prior ?? record;
  }
  if (!prior) throw new TypeError("journal observation has no dispatch intent");
  if (prior.terminalObserved && !sameFields(prior, record, [...keys])) {
    throw new TypeError("journal terminal result cannot be rolled back or replaced");
  }
  return sameFields(prior, record, [...keys]) ? prior : record;
}

async function syncDirectory(path) {
  const directory = await open(path, constants.O_RDONLY | (constants.O_DIRECTORY ?? 0) | (constants.O_NOFOLLOW ?? 0));
  try {
    if (!(await directory.stat()).isDirectory()) throw new TypeError("journal parent is not a directory");
    await directory.sync();
  } finally {
    await directory.close();
  }
}

async function ensureCanonicalPrivateParent(path) {
  const parent = dirname(path);
  const missing = [];
  let cursor = parent;
  for (;;) {
    try {
      if (!(await lstat(cursor)).isDirectory() || await realpath(cursor) !== resolve(cursor)) {
        throw new TypeError("browser journal parent path contains a symlink or non-directory");
      }
      break;
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
      missing.push(cursor);
      if (missing.length > 64 || dirname(cursor) === cursor) throw new TypeError("journal parent depth exceeded");
      cursor = dirname(cursor);
    }
  }
  // Synchronize the existing parent first. Errors here cannot be interpreted
  // as an absent journal, and no new file is created before this barrier.
  await syncDirectory(cursor);
  for (const directory of missing.reverse()) {
    await mkdir(directory, { mode: 0o700 });
    if (await realpath(directory) !== resolve(directory)) throw new TypeError("journal directory identity changed");
    await syncDirectory(directory);
    await syncDirectory(dirname(directory));
  }
}

export class MemoryBrowserOperationJournal {
  #records = new Map();

  async recordDispatch(record) {
    const snapshot = freezeRecord(requireRecord(record, "dispatch record"));
    const key = keyOf(snapshot);
    this.#records.set(key, advanceRecord("dispatch", this.#records.get(key), snapshot));
  }

  async recordObservation(record) {
    const snapshot = freezeRecord(requireRecord(record, "observation record"));
    const key = keyOf(snapshot);
    this.#records.set(key, advanceRecord("observation", this.#records.get(key), snapshot));
  }

  async getOperation(profileId, generation, operationId) {
    return this.#records.get(`${profileId}\u0000${generation}\u0000${operationId}`) ?? null;
  }

  async listOperations(profileId, generation) {
    const prefix = `${profileId}\u0000${generation}\u0000`;
    return [...this.#records.entries()]
      .filter(([key]) => key.startsWith(prefix))
      .map(([, value]) => value);
  }
}

export class FileBrowserOperationJournal {
  #path;
  #tail = Promise.resolve();
  #pending = 0;
  #parentReady = false;
  #poisoned = null;
  // Live-handle high-water mark, not an external anti-rollback authority.
  #frontier = null;
  // Reduction of that exact verified prefix; never a substitute for disk reads.
  #records = new Map();

  constructor(path) {
    if (typeof path !== "string" || !isAbsolute(path)) {
      throw new TypeError("browser journal path must be absolute");
    }
    this.#path = path;
  }

  async recordDispatch(record) {
    // Snapshot before the first await/queue boundary, not after another writer.
    const snapshot = freezeRecord(requireRecord(record, "dispatch record"));
    return this.#serialize(async () => {
      validateRecord(snapshot);
      const prior = await this.#getOperationUnlocked(snapshot.profileId, snapshot.generation, snapshot.operationId);
      const next = advanceRecord("dispatch", prior, snapshot);
      if (next !== prior) await this.#append({ type: "dispatch", record: next });
    });
  }

  async recordObservation(record) {
    const snapshot = freezeRecord(requireRecord(record, "observation record"));
    return this.#serialize(async () => {
      validateRecord(snapshot);
      const prior = await this.#getOperationUnlocked(snapshot.profileId, snapshot.generation, snapshot.operationId);
      const next = advanceRecord("observation", prior, snapshot);
      if (next !== prior) await this.#append({ type: "observation", record: next });
    });
  }

  async getOperation(profileId, generation, operationId) {
    return this.#serialize(() => this.#getOperationUnlocked(profileId, generation, operationId));
  }

  async listOperations(profileId, generation) {
    return this.#serialize(async () => {
      const records = await this.#load();
      const prefix = `${profileId}\u0000${generation}\u0000`;
      return [...records.entries()].filter(([key]) => key.startsWith(prefix)).map(([, value]) => value);
    });
  }

  async #getOperationUnlocked(profileId, generation, operationId) {
    const records = await this.#load();
    return records.get(`${profileId}\u0000${generation}\u0000${operationId}`) ?? null;
  }

  async #readView(handle) {
    if (await realpath(dirname(this.#path)) !== resolve(dirname(this.#path))) {
      throw new TypeError("browser journal parent path changed");
    }
    const info = await handle.stat({ bigint: true });
    if (!info.isFile() || info.size > BigInt(MAX_FILE_BYTES)) {
      throw new TypeError("browser journal is not a bounded regular file");
    }
    if (process.platform !== "win32" && (info.mode & 0o077n) !== 0n) {
      throw new TypeError("browser journal permissions are too broad");
    }
    // Read at most the admitted size plus one growth-detection byte. readFile
    // would allow a concurrently growing file to exceed the stat-time bound.
    const size = Number(info.size);
    const storage = Buffer.alloc(size + 1);
    let offset = 0;
    while (offset < storage.length) {
      const { bytesRead } = await handle.read(storage, offset,
        Math.min(64 * 1024, storage.length - offset), offset);
      if (bytesRead === 0) break;
      offset += bytesRead;
    }
    const after = await handle.stat({ bigint: true });
    const entry = await lstat(this.#path, { bigint: true });
    if (offset !== size || !entry.isFile()
        || entry.dev !== info.dev || entry.ino !== info.ino
        || entry.size !== info.size || entry.mtimeNs !== info.mtimeNs
        || entry.ctimeNs !== info.ctimeNs
        || after.dev !== info.dev || after.ino !== info.ino
        || after.size !== info.size || after.mtimeNs !== info.mtimeNs
        || after.ctimeNs !== info.ctimeNs
        || await realpath(dirname(this.#path)) !== resolve(dirname(this.#path))) {
      throw new TypeError("browser journal changed during bounded read");
    }
    const bytes = storage.subarray(0, size);
    return { bytes, dev: info.dev, ino: info.ino, size,
      digest: createHash("sha256").update(bytes).digest("hex") };
  }

  #checkFrontier(view, { exact = false } = {}) {
    const old = this.#frontier;
    if (!old) {
      if (exact && view.size !== 0) throw new TypeError("browser journal appeared before creation");
      return;
    }
    if (view.dev !== old.dev || view.ino !== old.ino || view.size < old.size
        || exact && view.size !== old.size
        || createHash("sha256").update(view.bytes.subarray(0, old.size)).digest("hex") !== old.digest) {
      throw new TypeError("browser journal identity or observed prefix changed; explicit owner recovery is required");
    }
  }

  #retainFrontier(view) {
    // Retain no second full journal buffer. The reduction can be reused only
    // after every current disk byte, file identity and old prefix are checked.
    this.#frontier = { dev: view.dev, ino: view.ino, size: view.size, digest: view.digest };
  }

  async #load() {
    try {
      return await this.#loadChecked();
    } catch (error) {
      this.#poisoned = error instanceof Error ? error : new Error("journal I/O failure");
      throw error;
    }
  }

  async #loadChecked() {
    const noFollow = constants.O_NOFOLLOW ?? 0;
    if (!this.#parentReady) {
      await ensureCanonicalPrivateParent(this.#path);
      this.#parentReady = true;
    }
    let handle;
    try {
      handle = await open(this.#path, constants.O_RDONLY | noFollow);
    } catch (error) {
      if (error?.code === "ENOENT" && this.#frontier === null) return this.#records;
      throw error;
    }
    let view;
    try {
      view = await this.#readView(handle);
      this.#checkFrontier(view);
    } finally {
      await handle.close();
    }
    // The verified frontier is always a complete UTF-8 line boundary. Parse
    // only new bytes, but keep the full bounded read/hash above on every use.
    const suffix = view.bytes.subarray(this.#frontier?.size ?? 0);
    const bytes = new TextDecoder("utf-8", { fatal: true }).decode(suffix);
    if (bytes.length !== 0 && !bytes.endsWith("\n")) {
      throw new TypeError("browser journal has an incomplete final record; explicit owner recovery is required");
    }
    // Do not publish a valid prefix of a malformed or semantically invalid
    // suffix. Stage only changed keys, not another copy of the whole history.
    const changes = new Map();
    const lines = bytes.length === 0 ? [] : bytes.split("\n");
    if (lines.at(-1) === "") lines.pop();
    for (const line of lines) {
      if (UTF8.encode(line).byteLength > MAX_LINE_BYTES) {
        throw new TypeError("browser journal line exceeds limit");
      }
      let envelope;
      try {
        envelope = JSON.parse(line);
      } catch {
        throw new TypeError("browser journal contains malformed JSON");
      }
      if (envelope.schema !== SCHEMA || envelope.version !== 1 || typeof envelope.checksum !== "string") {
        throw new TypeError("browser journal envelope is unsupported");
      }
      const unsigned = {
        schema: envelope.schema,
        version: envelope.version,
        type: envelope.type,
        record: envelope.record,
      };
      if (checksum(unsigned) !== envelope.checksum) {
        throw new TypeError("browser journal checksum mismatch");
      }
      const record = freezeRecord(requireRecord(envelope.record, "journal record"));
      const key = keyOf(record);
      const prior = changes.get(key) ?? this.#records.get(key);
      if (!["dispatch", "observation"].includes(envelope.type)) {
        throw new TypeError("browser journal record type is unsupported");
      }
      changes.set(key, advanceRecord(envelope.type, prior, record));
    }
    for (const [key, record] of changes) this.#records.set(key, record);
    this.#retainFrontier(view);
    return this.#records;
  }

  async #append({ type, record }) {
    const unsigned = { schema: SCHEMA, version: 1, type, record };
    const line = canonical({ ...unsigned, checksum: checksum(unsigned) }) + "\n";
    const lineBytes = UTF8.encode(line).byteLength;
    if (lineBytes > MAX_LINE_BYTES) {
      throw new TypeError("browser journal record exceeds line limit");
    }
    const noFollow = constants.O_NOFOLLOW ?? 0;
    // Never recreate a journal that this live handle has already observed.
    // First creation is exclusive; a racing creator must be reconciled.
    const creation = this.#frontier === null ? constants.O_CREAT | constants.O_EXCL : 0;
    const flags = constants.O_RDWR | constants.O_APPEND | creation | noFollow;
    let handle;
    let appended;
    try {
      if (await realpath(dirname(this.#path)) !== resolve(dirname(this.#path))) {
        throw new TypeError("browser journal parent path changed");
      }
      handle = await open(this.#path, flags, 0o600);
      const prior = await this.#readView(handle);
      // The reducer ran on this exact snapshot. Even valid concurrent growth
      // cannot be acknowledged using a now-stale predecessor decision.
      this.#checkFrontier(prior, { exact: true });
      if (prior.size + lineBytes > MAX_FILE_BYTES) {
        throw new TypeError("browser journal capacity exhausted");
      }
      await handle.writeFile(line, "utf8");
      await handle.sync();
      await syncDirectory(dirname(this.#path));
      appended = await this.#readView(handle);
      this.#checkFrontier(appended);
      if (appended.size !== prior.size + lineBytes
          || createHash("sha256").update(appended.bytes.subarray(0, prior.size)).digest("hex") !== prior.digest
          || !appended.bytes.subarray(prior.size).equals(Buffer.from(line, "utf8"))) {
        throw new TypeError("browser journal append observation changed");
      }
    } catch (error) {
      // A possible write/fsync failure is not an idempotent success. Preserve
      // bytes for recovery and reject all queued work through this same handle.
      this.#poisoned = error instanceof Error ? error : new Error("journal I/O failure");
      throw error;
    } finally {
      if (handle) {
        try { await handle.close(); }
        catch (error) { this.#poisoned = error instanceof Error ? error : new Error("journal I/O failure"); throw error; }
      }
    }
    // Publish only after write, both sync barriers, exact observation and close
    // succeed. A possible I/O failure poisons the handle before cache exposure.
    this.#records.set(keyOf(record), record);
    this.#retainFrontier(appended);
  }

  #serialize(operation) {
    if (this.#pending >= MAX_PENDING_OPERATIONS) {
      return Promise.reject(new TypeError("browser journal operation capacity occupied"));
    }
    this.#pending++;
    const run = this.#tail.catch(() => {}).then(() => {
      if (this.#poisoned) throw new Error(`browser journal requires explicit owner recovery: ${this.#poisoned.message}`);
      return operation();
    }).finally(() => { this.#pending--; });
    this.#tail = run.catch(() => {});
    return run;
  }
}

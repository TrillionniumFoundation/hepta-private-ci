import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { mkdir, open, realpath, rmdir } from "node:fs/promises";
import { dirname, isAbsolute, resolve } from "node:path";

const SCHEMA = "hepta.browser.operation-journal.v1";
const MAX_LINE_BYTES = 262_144;
const MAX_FILE_BYTES = 64 * 1024 * 1024;
const UTF8 = new TextEncoder();
const STRICT_UTF8 = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
const FILE_SERIALIZATION = new Map();

function fileIdentity(info) {
  return [info.dev, info.ino, info.size, info.mtimeNs, info.ctimeNs]
    .map(String)
    .join(":");
}

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

const MUTABLE_FIELDS = new Set([
  "status",
  "outcomeDigest",
  "terminalObserved",
  "observationReason",
]);
const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;

function freezeRecord(record) {
  requireRecord(record, "journal record");
  const snapshot = { ...record };
  for (const value of Object.values(snapshot)) {
    if (
      value !== null &&
      typeof value !== "string" &&
      typeof value !== "boolean" &&
      !(typeof value === "number" && Number.isSafeInteger(value))
    ) {
      throw new TypeError("journal record fields must be JSON scalars");
    }
  }
  for (const field of ["profileId", "operationId"]) {
    if (
      typeof snapshot[field] !== "string" ||
      !STABLE_ID.test(snapshot[field])
    ) {
      throw new TypeError(
        `journal ${field} must be a bounded stable identifier`,
      );
    }
  }
  if (!Number.isSafeInteger(snapshot.generation) || snapshot.generation < 1) {
    throw new TypeError("journal generation must be a positive safe integer");
  }
  for (const field of ["requestDigest", "semanticDigest"]) {
    if (
      typeof snapshot[field] !== "string" ||
      !DIGEST.test(snapshot[field]) ||
      snapshot[field] === "0".repeat(64)
    ) {
      throw new TypeError(
        `journal ${field} must be a non-zero lowercase SHA-256 digest`,
      );
    }
  }
  if (snapshot.terminalObserved === true) {
    if (
      (snapshot.status !== "succeeded" && snapshot.status !== "failed") ||
      typeof snapshot.outcomeDigest !== "string" ||
      !DIGEST.test(snapshot.outcomeDigest) ||
      snapshot.outcomeDigest === "0".repeat(64)
    ) {
      throw new TypeError("journal terminal result is invalid");
    }
  } else if (
    snapshot.terminalObserved !== false ||
    snapshot.status !== "indeterminate" ||
    snapshot.outcomeDigest !== null
  ) {
    throw new TypeError("journal indeterminate result is invalid");
  }
  return Object.freeze(snapshot);
}

function sameFields(left, right, excluded = new Set()) {
  const keys = new Set([...Object.keys(left), ...Object.keys(right)]);
  return [...keys].every(
    (key) =>
      excluded.has(key) ||
      (Object.hasOwn(left, key) === Object.hasOwn(right, key) &&
        left[key] === right[key]),
  );
}

function applyRecord(prior, record, type) {
  if (prior && !sameFields(prior, record, MUTABLE_FIELDS)) {
    throw new TypeError("journal operation changed immutable semantics");
  }
  if (type === "dispatch") {
    if (record.terminalObserved)
      throw new TypeError("journal dispatch must be indeterminate");
    // A repeated intent cannot erase progress already observed for that intent.
    return prior ?? record;
  }
  if (!prior) throw new TypeError("journal observation has no dispatch intent");
  if (prior.terminalObserved && !sameFields(prior, record)) {
    throw new TypeError(
      "journal terminal result cannot be changed or rolled back",
    );
  }
  return sameFields(prior, record) ? prior : record;
}

function requirePrivateFile(info) {
  if (!info.isFile() || info.size > MAX_FILE_BYTES) {
    throw new TypeError("browser journal is not a bounded regular file");
  }
  if (
    process.platform !== "win32" &&
    ((Number(info.mode) & 0o077) !== 0 ||
      Number(info.uid) !== process.getuid() ||
      Number(info.nlink) !== 1)
  ) {
    throw new TypeError(
      "browser journal permissions, owner or hard-link count are unsafe",
    );
  }
}

async function requirePrivateParent(path) {
  const flags =
    constants.O_RDONLY |
    (constants.O_DIRECTORY ?? 0) |
    (constants.O_NOFOLLOW ?? 0);
  const handle = await open(path, flags);
  try {
    const info = await handle.stat();
    if (
      !info.isDirectory() ||
      (process.platform !== "win32" &&
        ((info.mode & 0o022) !== 0 || info.uid !== process.getuid()))
    ) {
      throw new TypeError(
        "browser journal parent permissions or owner are unsafe",
      );
    }
  } finally {
    await handle.close();
  }
}

async function syncDirectory(path) {
  const flags =
    constants.O_RDONLY |
    (constants.O_DIRECTORY ?? 0) |
    (constants.O_NOFOLLOW ?? 0);
  const handle = await open(path, flags);
  try {
    if (!(await handle.stat()).isDirectory())
      throw new TypeError("journal parent is not a directory");
    await handle.sync();
  } finally {
    await handle.close();
  }
}

export class MemoryBrowserOperationJournal {
  #records = new Map();

  async recordDispatch(record) {
    const snapshot = freezeRecord(record);
    const key = keyOf(snapshot);
    this.#records.set(
      key,
      applyRecord(this.#records.get(key), snapshot, "dispatch"),
    );
  }

  async recordObservation(record) {
    const snapshot = freezeRecord(record);
    const key = keyOf(snapshot);
    this.#records.set(
      key,
      applyRecord(this.#records.get(key), snapshot, "observation"),
    );
  }

  async getOperation(profileId, generation, operationId) {
    return (
      this.#records.get(
        `${profileId}\u0000${generation}\u0000${operationId}`,
      ) ?? null
    );
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
  #parentInitialized = false;
  #uncertainWrite = null;
  #cacheIdentity = null;
  #cacheRecords = new Map();

  constructor(path) {
    if (typeof path !== "string" || !isAbsolute(path)) {
      throw new TypeError("browser journal path must be absolute");
    }
    this.#path = resolve(path);
  }

  async recordDispatch(record) {
    this.#assertHealthy();
    const snapshot = freezeRecord(record);
    return this.#serialize(async () => {
      const prior = await this.#getOperationUnlocked(
        snapshot.profileId,
        snapshot.generation,
        snapshot.operationId,
      );
      if (applyRecord(prior, snapshot, "dispatch") === prior) return;
      await this.#append({ type: "dispatch", record: snapshot });
    });
  }

  async recordObservation(record) {
    this.#assertHealthy();
    const snapshot = freezeRecord(record);
    return this.#serialize(async () => {
      const prior = await this.#getOperationUnlocked(
        snapshot.profileId,
        snapshot.generation,
        snapshot.operationId,
      );
      if (applyRecord(prior, snapshot, "observation") === prior) return;
      await this.#append({ type: "observation", record: snapshot });
    });
  }

  async getOperation(profileId, generation, operationId) {
    return this.#serialize(() =>
      this.#getOperationUnlocked(profileId, generation, operationId),
    );
  }

  async listOperations(profileId, generation) {
    return this.#serialize(async () => {
      const records = await this.#load();
      const prefix = `${profileId}\u0000${generation}\u0000`;
      return [...records.entries()]
        .filter(([key]) => key.startsWith(prefix))
        .map(([, value]) => value);
    });
  }

  async #getOperationUnlocked(profileId, generation, operationId) {
    const records = await this.#load();
    return (
      records.get(`${profileId}\u0000${generation}\u0000${operationId}`) ?? null
    );
  }

  async #load() {
    const noFollow = constants.O_NOFOLLOW ?? 0;
    let handle;
    await this.#prepareParent();
    try {
      handle = await open(this.#path, constants.O_RDONLY | noFollow);
    } catch (error) {
      if (error?.code === "ENOENT") {
        this.#cacheIdentity = null;
        this.#cacheRecords = new Map();
        return this.#cacheRecords;
      }
      throw error;
    }
    let bytes;
    let identity;
    try {
      const info = await handle.stat({ bigint: true });
      requirePrivateFile(info);
      identity = fileIdentity(info);
      if (identity === this.#cacheIdentity) return this.#cacheRecords;
      const raw = await handle.readFile();
      if (raw.length > MAX_FILE_BYTES)
        throw new TypeError("browser journal exceeds byte limit");
      try {
        bytes = STRICT_UTF8.decode(raw);
      } catch {
        throw new TypeError("browser journal is not valid UTF-8");
      }
    } finally {
      await handle.close();
    }
    if (bytes.length !== 0 && !bytes.endsWith("\n")) {
      throw new TypeError(
        "browser journal contains an incomplete trailing record",
      );
    }
    const records = new Map();
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
      if (
        envelope.schema !== SCHEMA ||
        envelope.version !== 1 ||
        typeof envelope.checksum !== "string"
      ) {
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
      const record = freezeRecord(
        requireRecord(envelope.record, "journal record"),
      );
      const key = keyOf(record);
      const prior = records.get(key);
      if (envelope.type !== "dispatch" && envelope.type !== "observation") {
        throw new TypeError("browser journal record type is unsupported");
      }
      records.set(key, applyRecord(prior, record, envelope.type));
    }
    this.#cacheIdentity = identity;
    this.#cacheRecords = records;
    return records;
  }

  async #append({ type, record }) {
    const unsigned = { schema: SCHEMA, version: 1, type, record };
    const line =
      canonical({ ...unsigned, checksum: checksum(unsigned) }) + "\n";
    const lineBytes = UTF8.encode(line).byteLength;
    if (lineBytes > MAX_LINE_BYTES) {
      throw new TypeError("browser journal record exceeds line limit");
    }
    await this.#prepareParent();
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const flags =
      constants.O_WRONLY | constants.O_APPEND | constants.O_CREAT | noFollow;
    // Once opening/creating the file starts, any failure can leave an uncertain
    // durable prefix. Fence this owner rather than treating a retry as success.
    try {
      const handle = await open(this.#path, flags, 0o600);
      let identity;
      try {
        const info = await handle.stat();
        requirePrivateFile(info);
        const before = fileIdentity(await handle.stat({ bigint: true }));
        if (
          (this.#cacheIdentity !== null && before !== this.#cacheIdentity) ||
          (this.#cacheIdentity === null && info.size !== 0)
        ) {
          throw new TypeError("browser journal changed during write admission");
        }
        if (info.size + lineBytes > MAX_FILE_BYTES) {
          throw new TypeError("browser journal capacity exhausted");
        }
        await handle.writeFile(line, "utf8");
        await handle.sync();
        identity = fileIdentity(await handle.stat({ bigint: true }));
      } finally {
        await handle.close();
      }
      await syncDirectory(dirname(this.#path));
      const key = keyOf(record);
      this.#cacheRecords.set(
        key,
        applyRecord(this.#cacheRecords.get(key), record, type),
      );
      this.#cacheIdentity = identity;
    } catch (error) {
      this.#uncertainWrite = error;
      throw error;
    }
  }

  async #prepareParent() {
    const parent = dirname(this.#path);
    if (this.#parentInitialized) {
      if ((await realpath(parent)) !== resolve(parent)) {
        throw new TypeError("browser journal parent path contains a symlink");
      }
      await requirePrivateParent(parent);
      return;
    }
    try {
      const firstCreated = await mkdir(parent, {
        recursive: true,
        mode: 0o700,
      });
      if ((await realpath(parent)) !== resolve(parent)) {
        throw new TypeError("browser journal parent path contains a symlink");
      }
      await requirePrivateParent(parent);
      // Persist every new directory and the entry that names it before a
      // dispatch can become visible to the worker.
      const last = firstCreated === undefined ? parent : dirname(firstCreated);
      let directory = parent;
      while (true) {
        await syncDirectory(directory);
        if (directory === last) break;
        directory = dirname(directory);
      }
      this.#parentInitialized = true;
    } catch (error) {
      this.#uncertainWrite = error;
      throw error;
    }
  }

  #assertHealthy() {
    if (this.#uncertainWrite) {
      throw new Error(
        "browser journal requires owner recovery after uncertain durability",
        {
          cause: this.#uncertainWrite,
        },
      );
    }
  }

  #serialize(operation) {
    const prior = FILE_SERIALIZATION.get(this.#path) ?? Promise.resolve();
    const run = prior
      .catch(() => {})
      .then(async () => {
        this.#assertHealthy();
        await this.#prepareParent();
        const lockPath = `${this.#path}.writer-lock`;
        try {
          await mkdir(lockPath, { mode: 0o700 });
        } catch (error) {
          if (error?.code === "EEXIST") {
            throw new Error(
              "browser journal writer lock is held; owner recovery may be required",
              { cause: error },
            );
          }
          throw error;
        }
        // Never steal an existing lock: a crashed writer requires owner recovery.
        try {
          return await operation();
        } finally {
          // A complete-looking page-cache tail after failed fsync is still
          // uncertain. Preserve the lock so a new instance cannot bless it.
          if (!this.#uncertainWrite) {
            try {
              await rmdir(lockPath);
            } catch (error) {
              this.#uncertainWrite = error;
              throw error;
            }
          }
        }
      });
    const tail = run.catch(() => {});
    FILE_SERIALIZATION.set(this.#path, tail);
    tail.then(() => {
      if (FILE_SERIALIZATION.get(this.#path) === tail)
        FILE_SERIALIZATION.delete(this.#path);
    });
    return run;
  }
}

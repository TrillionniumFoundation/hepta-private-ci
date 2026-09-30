import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { mkdir, open, realpath, unlink } from "node:fs/promises";
import { dirname, isAbsolute, resolve } from "node:path";

const SCHEMA = "hepta.browser.operation-journal.v1";
const MAX_LINE_BYTES = 262_144;
const MAX_FILE_BYTES = 64 * 1024 * 1024;
const UTF8 = new TextEncoder();
const FILE_QUEUES = new Map();

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
  record = { ...record };
  const id = /^[A-Za-z0-9._:-]{1,128}$/;
  const digest = /^[0-9a-f]{64}$/;
  if (
    typeof record.profileId !== "string" ||
    typeof record.operationId !== "string" ||
    !id.test(record.profileId) ||
    !id.test(record.operationId) ||
    !Number.isSafeInteger(record.generation) ||
    record.generation < 1 ||
    typeof record.requestDigest !== "string" ||
    typeof record.semanticDigest !== "string" ||
    !digest.test(record.requestDigest) ||
    !digest.test(record.semanticDigest) ||
    record.requestDigest === "0".repeat(64) ||
    record.semanticDigest === "0".repeat(64)
  ) {
    throw new TypeError("journal record identity or semantics are invalid");
  }
  const terminal = record.terminalObserved === true;
  if (
    (terminal &&
      ((record.status !== "succeeded" && record.status !== "failed") ||
        typeof record.outcomeDigest !== "string" ||
        !digest.test(record.outcomeDigest) ||
        record.outcomeDigest === "0".repeat(64))) ||
    (!terminal &&
      (record.terminalObserved !== false ||
        record.status !== "indeterminate" ||
        record.outcomeDigest !== null))
  ) {
    throw new TypeError("journal terminal observation is inconsistent");
  }
  return Object.freeze({ ...record });
}

const OBSERVATION_FIELDS = new Set([
  "status",
  "outcomeDigest",
  "terminalObserved",
  "observationReason",
]);

function requireSameSemantics(prior, record) {
  const keys = new Set([...Object.keys(prior), ...Object.keys(record)]);
  for (const key of keys) {
    if (!OBSERVATION_FIELDS.has(key) && prior[key] !== record[key]) {
      throw new TypeError("journal operation changed immutable semantics");
    }
  }
}

function applyObservation(prior, record) {
  if (!prior) throw new TypeError("journal observation has no dispatch intent");
  requireSameSemantics(prior, record);
  if (prior.terminalObserved === true) {
    if (
      record.terminalObserved !== true ||
      prior.status !== record.status ||
      prior.outcomeDigest !== record.outcomeDigest
    ) {
      throw new TypeError(
        "journal observation conflicts with an observed terminal result",
      );
    }
    return prior;
  }
  return freezeRecord({ ...prior, ...record });
}

async function syncDirectory(path) {
  const handle = await open(
    path,
    constants.O_RDONLY |
      (constants.O_DIRECTORY ?? 0) |
      (constants.O_NOFOLLOW ?? 0),
  );
  try {
    await handle.sync();
  } finally {
    await handle.close();
  }
}

async function ensureCanonicalPrivateParent(path) {
  const parent = dirname(path);
  const created = await mkdir(parent, { recursive: true, mode: 0o700 });
  const actual = await realpath(parent);
  if (actual !== resolve(parent)) {
    throw new TypeError("browser journal parent path contains a symlink");
  }
  if (created) {
    const barrier = dirname(created);
    for (let directory = parent; ; directory = dirname(directory)) {
      await syncDirectory(directory);
      if (directory === barrier) break;
    }
  }
}

export class MemoryBrowserOperationJournal {
  #records = new Map();

  async recordDispatch(record) {
    const snapshot = freezeRecord(requireRecord(record, "dispatch record"));
    if (snapshot.terminalObserved)
      throw new TypeError(
        "journal dispatch cannot claim a terminal observation",
      );
    const key = keyOf(snapshot);
    const prior = this.#records.get(key);
    if (prior) {
      requireSameSemantics(prior, snapshot);
      return;
    }
    this.#records.set(key, snapshot);
  }

  async recordObservation(record) {
    const snapshot = freezeRecord(requireRecord(record, "observation record"));
    const key = keyOf(snapshot);
    const prior = this.#records.get(key);
    this.#records.set(key, applyObservation(prior, snapshot));
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
  #parentReady = false;
  #needsRecovery = false;

  constructor(path) {
    if (typeof path !== "string" || !isAbsolute(path)) {
      throw new TypeError("browser journal path must be absolute");
    }
    this.#path = path;
  }

  async recordDispatch(record) {
    const snapshot = freezeRecord(requireRecord(record, "dispatch record"));
    if (snapshot.terminalObserved)
      throw new TypeError(
        "journal dispatch cannot claim a terminal observation",
      );
    return this.#serialize(async () => {
      const prior = await this.#getOperationUnlocked(
        snapshot.profileId,
        snapshot.generation,
        snapshot.operationId,
      );
      if (prior) {
        requireSameSemantics(prior, snapshot);
        return;
      }
      await this.#append({ type: "dispatch", record: snapshot });
    });
  }

  async recordObservation(record) {
    const snapshot = freezeRecord(requireRecord(record, "observation record"));
    return this.#serialize(async () => {
      const prior = await this.#getOperationUnlocked(
        snapshot.profileId,
        snapshot.generation,
        snapshot.operationId,
      );
      const next = applyObservation(prior, snapshot);
      if (next === prior || canonical(next) === canonical(prior)) return;
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
    await this.#ensureParent();
    const noFollow = constants.O_NOFOLLOW ?? 0;
    let handle;
    try {
      handle = await open(this.#path, constants.O_RDONLY | noFollow);
    } catch (error) {
      if (error?.code === "ENOENT") return new Map();
      throw error;
    }
    let bytes;
    try {
      const info = await handle.stat();
      if (!info.isFile() || info.size > MAX_FILE_BYTES) {
        throw new TypeError("browser journal is not a bounded regular file");
      }
      if (process.platform !== "win32" && (info.mode & 0o077) !== 0) {
        throw new TypeError("browser journal permissions are too broad");
      }
      bytes = await handle.readFile({ encoding: "utf8" });
    } finally {
      await handle.close();
    }
    if (bytes.length !== 0 && !bytes.endsWith("\n")) {
      throw new TypeError("browser journal has an incomplete trailing record");
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
      if (envelope.type === "dispatch") {
        if (record.terminalObserved)
          throw new TypeError(
            "journal dispatch cannot claim a terminal observation",
          );
        if (prior) {
          requireSameSemantics(prior, record);
        } else {
          records.set(key, record);
        }
      } else if (envelope.type === "observation") {
        records.set(key, applyObservation(prior, record));
      } else {
        throw new TypeError("browser journal record type is unsupported");
      }
    }
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
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const flags =
      constants.O_WRONLY | constants.O_APPEND | constants.O_CREAT | noFollow;
    const handle = await open(this.#path, flags, 0o600);
    try {
      const info = await handle.stat();
      if (!info.isFile()) {
        throw new TypeError("browser journal is not a regular file");
      }
      if (process.platform !== "win32" && (info.mode & 0o077) !== 0) {
        throw new TypeError("browser journal permissions are too broad");
      }
      if (info.size + lineBytes > MAX_FILE_BYTES) {
        throw new TypeError("browser journal capacity exhausted");
      }
      try {
        await handle.writeFile(line, "utf8");
        await handle.sync();
      } catch (error) {
        this.#needsRecovery = true;
        throw error;
      }
    } finally {
      try {
        await handle.close();
      } catch (error) {
        this.#needsRecovery = true;
        throw error;
      }
    }
    try {
      await syncDirectory(dirname(this.#path));
    } catch (error) {
      this.#needsRecovery = true;
      throw error;
    }
  }

  async #ensureParent() {
    if (this.#parentReady) return;
    try {
      await ensureCanonicalPrivateParent(this.#path);
      this.#parentReady = true;
    } catch (error) {
      this.#needsRecovery = true;
      throw error;
    }
  }

  #serialize(operation) {
    const preceding = FILE_QUEUES.get(this.#path) ?? Promise.resolve();
    const run = preceding.then(async () => {
      if (this.#needsRecovery)
        throw new TypeError("browser journal requires explicit owner recovery");
      await this.#ensureParent();
      const lockPath = this.#path + ".owner.lock";
      let lock;
      try {
        lock = await open(
          lockPath,
          constants.O_WRONLY |
            constants.O_CREAT |
            constants.O_EXCL |
            (constants.O_NOFOLLOW ?? 0),
          0o600,
        );
      } catch (error) {
        if (error?.code === "EEXIST") {
          throw new TypeError(
            "browser journal has an active owner or requires explicit owner recovery for incomplete or uncertain durability",
          );
        }
        throw error;
      }
      try {
        try {
          await lock.sync();
          await syncDirectory(dirname(this.#path));
        } catch (error) {
          this.#needsRecovery = true;
          throw error;
        }
        return await operation();
      } finally {
        try {
          await lock.close();
          if (!this.#needsRecovery) await unlink(lockPath);
        } catch (error) {
          this.#needsRecovery = true;
          throw error;
        }
      }
    });
    const settled = run.catch(() => {});
    FILE_QUEUES.set(this.#path, settled);
    void settled.then(() => {
      if (FILE_QUEUES.get(this.#path) === settled)
        FILE_QUEUES.delete(this.#path);
    });
    return run;
  }
}

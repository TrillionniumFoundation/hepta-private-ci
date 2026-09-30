import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { lstat, mkdir, open, realpath } from "node:fs/promises";
import { dirname, isAbsolute, resolve } from "node:path";

const SCHEMA = "hepta.browser.operation-journal.v1";
const MAX_LINE_BYTES = 262_144;
const MAX_FILE_BYTES = 64 * 1024 * 1024;
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
  return Object.freeze({ ...record });
}

function sameRecord(left, right) {
  return canonical(left) === canonical(right);
}

function requireSameSemantics(prior, next, message) {
  if (
    prior.requestDigest !== next.requestDigest ||
    prior.semanticDigest !== next.semanticDigest
  ) {
    throw new TypeError(message);
  }
}

function mergeObservation(prior, observation) {
  requireSameSemantics(
    prior,
    observation,
    "journal observation changed immutable semantics",
  );
  if (prior.terminalObserved === true) {
    if (observation.terminalObserved !== true || !sameRecord(prior, observation)) {
      throw new TypeError("journal terminal result cannot be changed or rolled back");
    }
    return prior;
  }
  return freezeRecord({ ...prior, ...observation });
}

async function syncDirectory(path) {
  if (process.platform === "win32") return;
  const noFollow = constants.O_NOFOLLOW ?? 0;
  const directory = constants.O_DIRECTORY ?? 0;
  const handle = await open(path, constants.O_RDONLY | directory | noFollow);
  try {
    const info = await handle.stat();
    if (!info.isDirectory()) {
      throw new TypeError("browser journal parent is not a directory");
    }
    await handle.sync();
  } finally {
    await handle.close();
  }
}

async function initializeCanonicalPrivateParent(path) {
  const parent = dirname(path);
  const missing = [];
  let existing = parent;
  for (;;) {
    try {
      const info = await lstat(existing);
      if (!info.isDirectory()) {
        throw new TypeError("browser journal parent is not a directory");
      }
      break;
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
      missing.push(existing);
      const next = dirname(existing);
      if (next === existing) throw error;
      existing = next;
    }
  }
  await mkdir(parent, { recursive: true, mode: 0o700 });
  const actual = await realpath(parent);
  if (actual !== resolve(parent)) {
    throw new TypeError("browser journal parent path contains a symlink");
  }
  for (const directory of [existing, ...missing.reverse()]) {
    await syncDirectory(directory);
  }
}

export class MemoryBrowserOperationJournal {
  #records = new Map();

  async recordDispatch(record) {
    const snapshot = freezeRecord(requireRecord(record, "dispatch record"));
    const key = keyOf(snapshot);
    const prior = this.#records.get(key);
    if (prior) {
      requireSameSemantics(
        prior,
        snapshot,
        "journal operation identity was reused with changed semantics",
      );
      return prior;
    }
    this.#records.set(key, snapshot);
    return snapshot;
  }

  async recordObservation(record) {
    const snapshot = freezeRecord(requireRecord(record, "observation record"));
    const key = keyOf(snapshot);
    const prior = this.#records.get(key);
    if (!prior) throw new TypeError("journal observation has no dispatch intent");
    const merged = mergeObservation(prior, snapshot);
    this.#records.set(key, merged);
    return merged;
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
  #fencedError = null;
  #parentReady = false;

  constructor(path) {
    if (typeof path !== "string" || !isAbsolute(path)) {
      throw new TypeError("browser journal path must be absolute");
    }
    this.#path = path;
  }

  async recordDispatch(record) {
    const snapshot = freezeRecord(requireRecord(record, "dispatch record"));
    return this.#serialize(async () => {
      const prior = await this.#getOperationUnlocked(
        snapshot.profileId,
        snapshot.generation,
        snapshot.operationId,
      );
      if (prior) {
        requireSameSemantics(
          prior,
          snapshot,
          "journal operation identity was reused with changed semantics",
        );
        return prior;
      }
      await this.#append({ type: "dispatch", record: snapshot });
      return snapshot;
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
      if (!prior) {
        throw new TypeError("journal observation has no dispatch intent");
      }
      const merged = mergeObservation(prior, snapshot);
      if (sameRecord(prior, merged)) return prior;
      await this.#append({ type: "observation", record: snapshot });
      return merged;
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

  async #ensureParent() {
    if (this.#parentReady) return;
    try {
      await initializeCanonicalPrivateParent(this.#path);
      this.#parentReady = true;
    } catch (error) {
      this.#fence(error);
      throw error;
    }
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
    if (bytes.length > 0 && !bytes.endsWith("\n")) {
      throw new TypeError("browser journal contains an incomplete trailing record");
    }
    const records = new Map();
    const lines = bytes.length === 0 ? [] : bytes.slice(0, -1).split("\n");
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
      const record = freezeRecord(requireRecord(envelope.record, "journal record"));
      const key = keyOf(record);
      const prior = records.get(key);
      if (envelope.type === "dispatch") {
        if (prior) {
          requireSameSemantics(
            prior,
            record,
            "browser journal contains conflicting dispatch semantics",
          );
          continue;
        }
        records.set(key, record);
      } else if (envelope.type === "observation") {
        if (!prior) {
          throw new TypeError("browser journal observation precedes dispatch");
        }
        records.set(key, mergeObservation(prior, record));
      } else {
        throw new TypeError("browser journal record type is unsupported");
      }
    }
    return records;
  }

  async #append({ type, record }) {
    const unsigned = { schema: SCHEMA, version: 1, type, record };
    const line = canonical({ ...unsigned, checksum: checksum(unsigned) }) + "\n";
    const lineBytes = UTF8.encode(line).byteLength;
    if (lineBytes > MAX_LINE_BYTES) {
      throw new TypeError("browser journal record exceeds line limit");
    }
    await this.#ensureParent();
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const flags =
      constants.O_WRONLY | constants.O_APPEND | constants.O_CREAT | noFollow;
    const handle = await open(this.#path, flags, 0o600);
    let uncertain = false;
    let failure = null;
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
      uncertain = true;
      await handle.writeFile(line, "utf8");
      await handle.sync();
    } catch (error) {
      failure = error;
    }
    try {
      await handle.close();
    } catch (error) {
      failure ??= error;
      uncertain = true;
    }
    if (failure) {
      if (uncertain) this.#fence(failure);
      throw failure;
    }
    try {
      await syncDirectory(dirname(this.#path));
    } catch (error) {
      this.#fence(error);
      throw error;
    }
  }

  #fence(error) {
    this.#fencedError ??= error;
  }

  #assertHealthy() {
    if (this.#fencedError) {
      throw new TypeError(
        "browser journal owner recovery is required after uncertain I/O",
        { cause: this.#fencedError },
      );
    }
  }

  #serialize(operation) {
    const run = this.#tail.catch(() => {}).then(async () => {
      this.#assertHealthy();
      return operation();
    });
    this.#tail = run.catch(() => {});
    return run;
  }
}

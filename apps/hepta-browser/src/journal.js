import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { mkdir, open, realpath } from "node:fs/promises";
import { dirname, isAbsolute, parse, resolve, sep } from "node:path";
import { isDeepStrictEqual } from "node:util";

const SCHEMA = "hepta.browser.operation-journal.v1";
const MAX_LINE_BYTES = 262_144;
const MAX_FILE_BYTES = 64 * 1024 * 1024;
const UTF8 = new TextEncoder();
const OBSERVATION_FIELDS = new Set([
  "status",
  "terminalObserved",
  "outcomeDigest",
  "observationReason",
]);

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

function deepFreeze(value) {
  if (value === null || typeof value !== "object" || Object.isFrozen(value)) return value;
  for (const child of Object.values(value)) deepFreeze(child);
  return Object.freeze(value);
}

function snapshotRecord(value, name) {
  requireRecord(value, name);
  let snapshot;
  try {
    snapshot = structuredClone(value);
  } catch (error) {
    throw new TypeError(`${name} must contain cloneable data`, { cause: error });
  }
  return deepFreeze(requireRecord(snapshot, name));
}

function immutableProjection(record) {
  return Object.fromEntries(
    Object.entries(record).filter(([name]) => !OBSERVATION_FIELDS.has(name)),
  );
}

function assertSameSemantics(prior, next) {
  if (!isDeepStrictEqual(immutableProjection(prior), immutableProjection(next))) {
    throw new TypeError("journal operation identity was reused with changed immutable semantics");
  }
}

function applyDispatch(records, snapshot) {
  const key = keyOf(snapshot);
  const prior = records.get(key);
  if (prior) {
    assertSameSemantics(prior, snapshot);
    return false;
  }
  records.set(key, snapshot);
  return true;
}

function applyObservation(records, snapshot) {
  const key = keyOf(snapshot);
  const prior = records.get(key);
  if (!prior) throw new TypeError("journal observation has no dispatch intent");
  assertSameSemantics(prior, snapshot);
  const merged = snapshotRecord({ ...prior, ...snapshot }, "merged observation record");
  if (prior.terminalObserved === true) {
    if (snapshot.terminalObserved !== true || !isDeepStrictEqual(prior, merged)) {
      throw new TypeError("journal terminal observation cannot be changed or rolled back");
    }
    return false;
  }
  if (isDeepStrictEqual(prior, merged)) return false;
  records.set(key, merged);
  return true;
}

function pathComponents(path) {
  const absolute = resolve(path);
  const root = parse(absolute).root;
  const names = absolute.slice(root.length).split(sep).filter(Boolean);
  const output = [];
  let current = root;
  for (const name of names) {
    current = resolve(current, name);
    output.push(current);
  }
  return output;
}

async function closePreserving(handle, primaryError) {
  try {
    await handle.close();
    return primaryError;
  } catch (closeError) {
    return primaryError ?? closeError;
  }
}

async function syncDirectory(path) {
  const noFollow = constants.O_NOFOLLOW ?? 0;
  const directory = constants.O_DIRECTORY ?? 0;
  const handle = await open(path, constants.O_RDONLY | directory | noFollow);
  let error = null;
  try {
    const info = await handle.stat();
    if (!info.isDirectory()) throw new TypeError("browser journal parent is not a directory");
    await handle.sync();
  } catch (caught) {
    error = caught;
  }
  error = await closePreserving(handle, error);
  if (error) throw error;
}

async function ensureCanonicalPrivateParent(path, onMutation) {
  const parent = resolve(dirname(path));
  for (const component of pathComponents(parent)) {
    let created = false;
    try {
      await mkdir(component, { mode: 0o700 });
      created = true;
      onMutation();
    } catch (error) {
      if (error?.code !== "EEXIST") throw error;
    }
    const actual = await realpath(component);
    if (actual !== component) {
      throw new TypeError("browser journal parent path contains a symlink");
    }
    if (created) await syncDirectory(dirname(component));
  }
  return parent;
}

async function validateCanonicalParent(path) {
  const parent = resolve(dirname(path));
  const actual = await realpath(parent);
  if (actual !== parent) {
    throw new TypeError("browser journal parent path contains a symlink");
  }
  return parent;
}

export class MemoryBrowserOperationJournal {
  #records = new Map();

  async recordDispatch(record) {
    const snapshot = snapshotRecord(record, "dispatch record");
    applyDispatch(this.#records, snapshot);
  }

  async recordObservation(record) {
    const snapshot = snapshotRecord(record, "observation record");
    applyObservation(this.#records, snapshot);
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
  #parentReady = false;
  #recoveryCause = null;

  constructor(path) {
    if (typeof path !== "string" || !isAbsolute(path)) {
      throw new TypeError("browser journal path must be absolute");
    }
    this.#path = resolve(path);
  }

  async recordDispatch(record) {
    const snapshot = snapshotRecord(record, "dispatch record");
    return this.#serialize(async () => {
      const records = await this.#load();
      if (!applyDispatch(records, snapshot)) return;
      await this.#append({ type: "dispatch", record: snapshot });
    });
  }

  async recordObservation(record) {
    const snapshot = snapshotRecord(record, "observation record");
    return this.#serialize(async () => {
      const records = await this.#load();
      if (!applyObservation(records, snapshot)) return;
      await this.#append({ type: "observation", record: snapshot });
    });
  }

  async getOperation(profileId, generation, operationId) {
    const key = `${profileId}\u0000${generation}\u0000${operationId}`;
    return this.#serialize(async () => (await this.#load()).get(key) ?? null);
  }

  async listOperations(profileId, generation) {
    const prefix = `${profileId}\u0000${generation}\u0000`;
    return this.#serialize(async () =>
      [...(await this.#load()).entries()]
        .filter(([key]) => key.startsWith(prefix))
        .map(([, value]) => value),
    );
  }

  async #load() {
    const noFollow = constants.O_NOFOLLOW ?? 0;
    let handle;
    try {
      handle = await open(this.#path, constants.O_RDONLY | noFollow);
    } catch (error) {
      if (error?.code === "ENOENT") return new Map();
      throw error;
    }
    let bytes;
    let error = null;
    try {
      await validateCanonicalParent(this.#path);
      const info = await handle.stat();
      if (!info.isFile() || info.size > MAX_FILE_BYTES) {
        throw new TypeError("browser journal is not a bounded regular file");
      }
      if (process.platform !== "win32" && (info.mode & 0o077) !== 0) {
        throw new TypeError("browser journal permissions are too broad");
      }
      bytes = await handle.readFile({ encoding: "utf8" });
    } catch (caught) {
      error = caught;
    }
    error = await closePreserving(handle, error);
    if (error) throw error;
    if (bytes.length > 0 && !bytes.endsWith("\n")) {
      throw new TypeError("browser journal contains an incomplete final record");
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
      const record = snapshotRecord(envelope.record, "journal record");
      if (envelope.type === "dispatch") {
        applyDispatch(records, record);
      } else if (envelope.type === "observation") {
        applyObservation(records, record);
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

    let mutationStarted = false;
    const markMutation = () => { mutationStarted = true; };
    let handle = null;
    let error = null;
    let parent;
    try {
      if (this.#parentReady) {
        parent = await validateCanonicalParent(this.#path);
      } else {
        parent = await ensureCanonicalPrivateParent(this.#path, markMutation);
        this.#parentReady = true;
      }
      const noFollow = constants.O_NOFOLLOW ?? 0;
      try {
        handle = await open(
          this.#path,
          constants.O_WRONLY | constants.O_APPEND | constants.O_CREAT | constants.O_EXCL | noFollow,
          0o600,
        );
        markMutation();
      } catch (caught) {
        if (caught?.code !== "EEXIST") throw caught;
        handle = await open(this.#path, constants.O_WRONLY | constants.O_APPEND | noFollow);
      }
      const info = await handle.stat();
      if (!info.isFile()) throw new TypeError("browser journal is not a regular file");
      if (process.platform !== "win32" && (info.mode & 0o077) !== 0) {
        throw new TypeError("browser journal permissions are too broad");
      }
      if (info.size + lineBytes > MAX_FILE_BYTES) {
        throw new TypeError("browser journal capacity exhausted");
      }
      markMutation();
      await handle.writeFile(line, "utf8");
      await handle.sync();
    } catch (caught) {
      error = caught;
    }
    if (handle) error = await closePreserving(handle, error);
    if (!error) {
      try {
        await syncDirectory(parent);
      } catch (caught) {
        error = caught;
      }
    }
    if (error) {
      if (mutationStarted) this.#recoveryCause ??= error;
      throw error;
    }
  }

  #assertHealthy() {
    if (!this.#recoveryCause) return;
    throw new Error("browser journal owner recovery is required after an uncertain durable mutation", {
      cause: this.#recoveryCause,
    });
  }

  #serialize(operation) {
    const run = this.#tail.then(async () => {
      this.#assertHealthy();
      return operation();
    });
    this.#tail = run.catch(() => {});
    return run;
  }
}

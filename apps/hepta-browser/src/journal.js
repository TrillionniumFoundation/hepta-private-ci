import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { mkdir, open, realpath } from "node:fs/promises";
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

async function ensureCanonicalPrivateParent(path) {
  const parent = dirname(path);
  await mkdir(parent, { recursive: true, mode: 0o700 });
  const actual = await realpath(parent);
  if (actual !== resolve(parent)) {
    throw new TypeError("browser journal parent path contains a symlink");
  }
}

export class MemoryBrowserOperationJournal {
  #records = new Map();

  async recordDispatch(record) {
    const snapshot = freezeRecord(requireRecord(record, "dispatch record"));
    const key = keyOf(snapshot);
    const prior = this.#records.get(key);
    if (prior && prior.requestDigest !== snapshot.requestDigest) {
      throw new TypeError("journal operation identity was reused with changed semantics");
    }
    this.#records.set(key, snapshot);
  }

  async recordObservation(record) {
    const snapshot = freezeRecord(requireRecord(record, "observation record"));
    const key = keyOf(snapshot);
    const prior = this.#records.get(key);
    if (!prior) throw new TypeError("journal observation has no dispatch intent");
    if (prior.requestDigest !== snapshot.requestDigest || prior.semanticDigest !== snapshot.semanticDigest) {
      throw new TypeError("journal observation changed immutable semantics");
    }
    this.#records.set(key, freezeRecord({ ...prior, ...snapshot }));
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

  constructor(path) {
    if (typeof path !== "string" || !isAbsolute(path)) {
      throw new TypeError("browser journal path must be absolute");
    }
    this.#path = path;
  }

  async recordDispatch(record) {
    return this.#serialize(async () => {
      const prior = await this.#getOperationUnlocked(record.profileId, record.generation, record.operationId);
      if (prior && prior.requestDigest !== record.requestDigest) {
        throw new TypeError("journal operation identity was reused with changed semantics");
      }
      await this.#append({ type: "dispatch", record: requireRecord(record, "dispatch record") });
    });
  }

  async recordObservation(record) {
    return this.#serialize(async () => {
      const prior = await this.#getOperationUnlocked(record.profileId, record.generation, record.operationId);
      if (!prior) throw new TypeError("journal observation has no dispatch intent");
      if (prior.requestDigest !== record.requestDigest || prior.semanticDigest !== record.semanticDigest) {
        throw new TypeError("journal observation changed immutable semantics");
      }
      await this.#append({ type: "observation", record: requireRecord(record, "observation record") });
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

  async #load() {
    const noFollow = constants.O_NOFOLLOW ?? 0;
    let handle;
    try {
      await ensureCanonicalPrivateParent(this.#path);
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
      const prior = records.get(key);
      if (envelope.type === "dispatch") {
        if (prior && prior.requestDigest !== record.requestDigest) {
          throw new TypeError("browser journal contains conflicting dispatch identity");
        }
        records.set(key, record);
      } else if (envelope.type === "observation") {
        if (!prior) throw new TypeError("browser journal observation precedes dispatch");
        if (prior.requestDigest !== record.requestDigest || prior.semanticDigest !== record.semanticDigest) {
          throw new TypeError("browser journal observation changed semantics");
        }
        records.set(key, freezeRecord({ ...prior, ...record }));
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
    await ensureCanonicalPrivateParent(this.#path);
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const flags = constants.O_WRONLY | constants.O_APPEND | constants.O_CREAT | noFollow;
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
      await handle.writeFile(line, "utf8");
      await handle.sync();
    } finally {
      await handle.close();
    }
  }

  #serialize(operation) {
    const run = this.#tail.catch(() => {}).then(operation);
    this.#tail = run.catch(() => {});
    return run;
  }
}

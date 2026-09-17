import { mkdir, open, readFile, rename, stat, chmod, lstat } from "node:fs/promises";
import { dirname, isAbsolute, resolve } from "node:path";

const JOURNAL_SCHEMA = "hepta.browser.operation-journal.v1";
const MAX_JOURNAL_BYTES = 16 * 1024 * 1024;
const MAX_OPERATION_RECORDS = 16_384;

function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

function clone(value) {
  return structuredClone(value);
}

function profileKey(profileId, generation) {
  return `${encodeURIComponent(profileId)}#${generation}`;
}

function emptyState() {
  return {
    schema: JOURNAL_SCHEMA,
    revision: 0,
    profiles: {},
  };
}

export class FileBrowserOperationJournal {
  durable = true;
  #path;
  #state = null;
  #writeTail = Promise.resolve();
  #counter = 0;

  constructor(path) {
    if (typeof path !== "string" || !isAbsolute(path)) {
      throw new TypeError("browser operation journal path must be absolute");
    }
    this.#path = resolve(path);
  }

  async loadOutstandingOperations({ profileId, generation }) {
    const state = await this.#load();
    const profile = state.profiles[profileKey(profileId, generation)];
    if (!profile) {
      return [];
    }
    return Object.values(profile.operations)
      .filter((operation) => operation.receipt?.terminalObserved !== true)
      .map(clone);
  }

  async findOperation({ profileId, generation, operationId }) {
    const state = await this.#load();
    const operation =
      state.profiles[profileKey(profileId, generation)]?.operations?.[operationId];
    return operation ? clone(operation) : null;
  }

  async recordIntent(record) {
    return this.#mutate((state) => {
      requireRecord(record, "journal intent");
      const key = profileKey(record.profileId, record.generation);
      const profile = (state.profiles[key] ??= { operations: {} });
      const existing = profile.operations[record.operationId];
      if (existing) {
        if (existing.semanticDigest !== record.semanticDigest) {
          throw new TypeError("journal operation identity conflicts with durable semantics");
        }
        return;
      }
      if (this.#operationCount(state) >= MAX_OPERATION_RECORDS) {
        throw new TypeError("browser operation journal capacity is exhausted");
      }
      profile.operations[record.operationId] = clone(record);
    });
  }

  async recordObservation({ profileId, generation, operationId, receipt }) {
    return this.#mutate((state) => {
      const key = profileKey(profileId, generation);
      const operation = state.profiles[key]?.operations?.[operationId];
      if (!operation) {
        throw new TypeError("cannot observe an operation without a durable intent");
      }
      operation.receipt = clone(receipt);
      operation.updatedAtMs = Date.now();
    });
  }

  async #mutate(mutator) {
    const run = async () => {
      const state = await this.#load();
      mutator(state);
      state.revision += 1;
      await this.#persist(state);
    };
    const result = this.#writeTail.then(run, run);
    this.#writeTail = result.catch(() => {});
    return result;
  }

  async #load() {
    if (this.#state) {
      return this.#state;
    }
    await mkdir(dirname(this.#path), { recursive: true, mode: 0o700 });
    let payload;
    try {
      const linkMetadata = await lstat(this.#path);
      if (linkMetadata.isSymbolicLink() || !linkMetadata.isFile() || linkMetadata.nlink !== 1) {
        throw new TypeError("browser operation journal must be one regular non-symlink file");
      }
      payload = await readFile(this.#path);
    } catch (error) {
      if (error?.code === "ENOENT") {
        this.#state = emptyState();
        return this.#state;
      }
      throw error;
    }
    if (payload.byteLength > MAX_JOURNAL_BYTES) {
      throw new TypeError("browser operation journal exceeds its byte limit");
    }
    let parsed;
    try {
      parsed = JSON.parse(payload.toString("utf8"));
    } catch {
      throw new TypeError("browser operation journal is malformed");
    }
    requireRecord(parsed, "browser operation journal");
    if (parsed.schema !== JOURNAL_SCHEMA || !Number.isSafeInteger(parsed.revision)) {
      throw new TypeError("browser operation journal schema is unsupported");
    }
    requireRecord(parsed.profiles, "browser operation journal profiles");
    if (this.#operationCount(parsed) > MAX_OPERATION_RECORDS) {
      throw new TypeError("browser operation journal exceeds its operation limit");
    }
    if (process.platform !== "win32") {
      const metadata = await stat(this.#path);
      if ((metadata.mode & 0o077) !== 0) {
        throw new TypeError("browser operation journal must not be group/world accessible");
      }
    }
    this.#state = parsed;
    return this.#state;
  }

  #operationCount(state) {
    return Object.values(state.profiles).reduce(
      (count, profile) => count + Object.keys(profile.operations ?? {}).length,
      0,
    );
  }

  async #persist(state) {
    const encoded = Buffer.from(JSON.stringify(state), "utf8");
    if (encoded.byteLength > MAX_JOURNAL_BYTES) {
      throw new TypeError("browser operation journal exceeds its byte limit");
    }
    const parent = dirname(this.#path);
    await mkdir(parent, { recursive: true, mode: 0o700 });
    const temporary = `${this.#path}.tmp-${process.pid}-${this.#counter++}`;
    const handle = await open(temporary, "wx", 0o600);
    try {
      await handle.writeFile(encoded);
      await handle.sync();
    } finally {
      await handle.close();
    }
    await chmod(temporary, 0o600);
    await rename(temporary, this.#path);
    const parentHandle = await open(parent, "r");
    try {
      await parentHandle.sync();
    } finally {
      await parentHandle.close();
    }
    this.#state = state;
  }
}

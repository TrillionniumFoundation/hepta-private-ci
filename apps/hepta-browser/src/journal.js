import { createHash, randomUUID } from "node:crypto";
import { constants } from "node:fs";
import {
  lstat,
  mkdir,
  open,
  readFile,
  rename,
  rm,
} from "node:fs/promises";
import { dirname } from "node:path";

import {
  FileBrowserOperationJournal as CoreFileBrowserOperationJournal,
  MemoryBrowserOperationJournal as CoreMemoryBrowserOperationJournal,
} from "./journal-core.js";

const SCHEMA = "hepta.browser.operation-journal.v2";
const MAX_LOCK_BYTES = 4096;
const DEFAULT_STALE_LOCK_MS = 30_000;
const IO_FENCE_CODES = new Set([
  "EBADF",
  "EDQUOT",
  "EFBIG",
  "EIO",
  "EMFILE",
  "ENFILE",
  "ENOSPC",
  "ENXIO",
  "EROFS",
  "ESTALE",
]);

function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

function keyOf(record) {
  return `${record.profileId}\u0000${record.generation}\u0000${record.operationId}`;
}

function prefixOf(profileId, generation) {
  return `${profileId}\u0000${generation}\u0000`;
}

function canonical(value) {
  return JSON.stringify(value);
}

function checksum(value) {
  return createHash("sha256").update(canonical(value)).digest("hex");
}

function sameIdentity(left, right) {
  return (
    left.requestDigest === right.requestDigest &&
    left.semanticDigest === right.semanticDigest
  );
}

function sameRecord(left, right) {
  return canonical(left) === canonical(right);
}

function immutableIdentity(prior, record, message) {
  if (!sameIdentity(prior, record)) {
    throw new TypeError(message);
  }
}

function foldDispatch(prior, record) {
  if (!prior) return { record, duplicate: false };
  immutableIdentity(
    prior,
    record,
    "journal operation identity was reused with changed semantics",
  );
  return { record: prior, duplicate: true };
}

function foldObservation(prior, record) {
  if (!prior) {
    throw new TypeError("journal observation has no dispatch intent");
  }
  immutableIdentity(
    prior,
    record,
    "journal observation changed immutable semantics",
  );
  if (sameRecord(prior, record)) {
    return { record: prior, duplicate: true };
  }
  if (prior.terminalObserved === true) {
    throw new TypeError(
      "journal observation conflicts with an already observed terminal result",
    );
  }
  return { record, duplicate: false };
}

function foldSnapshot(prior, record) {
  if (!prior) return { record, duplicate: false };
  immutableIdentity(
    prior,
    record,
    "journal snapshot conflicts with prior immutable semantics",
  );
  if (sameRecord(prior, record)) {
    return { record: prior, duplicate: true };
  }
  if (prior.terminalObserved === true) {
    throw new TypeError(
      "journal snapshot conflicts with an already observed terminal result",
    );
  }
  return { record, duplicate: false };
}

function foldRecord(prior, type, record) {
  if (type === "dispatch") return foldDispatch(prior, record);
  if (type === "observation") return foldObservation(prior, record);
  if (type === "snapshot") return foldSnapshot(prior, record);
  throw new TypeError("browser journal record type is unsupported");
}

function isIoFailure(error) {
  return typeof error?.code === "string" && IO_FENCE_CODES.has(error.code);
}

function ownerLockedError(message) {
  const error = new Error(message);
  error.name = "BrowserJournalOwnerLockedError";
  error.code = "BROWSER_JOURNAL_OWNER_LOCKED";
  return error;
}

async function syncParent(path) {
  const noFollow = constants.O_NOFOLLOW ?? 0;
  const handle = await open(dirname(path), constants.O_RDONLY | noFollow);
  try {
    await handle.sync();
  } finally {
    await handle.close();
  }
}

export class MemoryBrowserOperationJournal extends CoreMemoryBrowserOperationJournal {
  async recordDispatch(record) {
    const snapshot = Object.freeze({ ...requireRecord(record, "dispatch record") });
    const prior = await super.getOperation(
      snapshot.profileId,
      snapshot.generation,
      snapshot.operationId,
    );
    if (foldDispatch(prior, snapshot).duplicate) return;
    await super.recordDispatch(snapshot);
  }

  async recordObservation(record) {
    const snapshot = Object.freeze({ ...requireRecord(record, "observation record") });
    const prior = await super.getOperation(
      snapshot.profileId,
      snapshot.generation,
      snapshot.operationId,
    );
    if (foldObservation(prior, snapshot).duplicate) return;
    await super.recordObservation(snapshot);
  }
}

export class FileBrowserOperationJournal extends CoreFileBrowserOperationJournal {
  #path;
  #lockPath;
  #ownerLockStaleMs;
  #tail = Promise.resolve();
  #fenced = null;

  constructor(path, options = {}) {
    const {
      ownerLockStaleMs = DEFAULT_STALE_LOCK_MS,
      ...coreOptions
    } = options;
    super(path, coreOptions);
    if (!Number.isSafeInteger(ownerLockStaleMs) || ownerLockStaleMs < 1) {
      throw new TypeError("ownerLockStaleMs must be a positive safe integer");
    }
    this.#path = path;
    this.#lockPath = `${path}.owner.lock`;
    this.#ownerLockStaleMs = ownerLockStaleMs;
  }

  async assertProfileGenerationAvailable(profileId, generation) {
    return this.#run(async () => {
      await this.#projectAndMigrate();
      return super.assertProfileGenerationAvailable(profileId, generation);
    });
  }

  async recordDispatch(record) {
    const snapshot = Object.freeze({ ...requireRecord(record, "dispatch record") });
    return this.#run(async () => {
      const records = await this.#projectAndMigrate();
      const prior = records.get(keyOf(snapshot));
      if (foldDispatch(prior, snapshot).duplicate) return;
      await super.recordDispatch(snapshot);
    });
  }

  async recordObservation(record) {
    const snapshot = Object.freeze({ ...requireRecord(record, "observation record") });
    return this.#run(async () => {
      const records = await this.#projectAndMigrate();
      const prior = records.get(keyOf(snapshot));
      if (foldObservation(prior, snapshot).duplicate) return;
      await super.recordObservation(snapshot);
    });
  }

  async getOperation(profileId, generation, operationId) {
    return this.#run(async () => {
      const records = await this.#projectAndMigrate();
      return records.get(`${profileId}\u0000${generation}\u0000${operationId}`) ?? null;
    });
  }

  async listOperations(profileId, generation) {
    return this.#run(async () => {
      const records = await this.#projectAndMigrate();
      const prefix = prefixOf(profileId, generation);
      return [...records.entries()]
        .filter(([key]) => key.startsWith(prefix))
        .map(([, value]) => value);
    });
  }

  async compact() {
    return this.#run(async () => {
      await this.#projectAndMigrate();
      return super.compact();
    });
  }

  async retireProfile(profileId, generation) {
    return this.#run(async () => {
      await this.#projectAndMigrate();
      return super.retireProfile(profileId, generation);
    });
  }

  #run(operation) {
    if (this.#fenced) {
      const error = new Error(
        `browser journal owner is fenced pending restart/recovery: ${this.#fenced.message}`,
      );
      error.name = "BrowserJournalFencedError";
      error.code = "BROWSER_JOURNAL_FENCED";
      return Promise.reject(error);
    }
    const run = this.#tail
      .catch(() => {})
      .then(() => this.#withOwnerLock(operation));
    this.#tail = run.catch(() => {});
    return run;
  }

  async #withOwnerLock(operation) {
    const owner = await this.#acquireOwnerLock();
    let result;
    let failure = null;
    try {
      result = await operation();
    } catch (error) {
      failure = error;
    }
    try {
      await this.#releaseOwnerLock(owner);
    } catch (error) {
      failure ??= error;
    }
    if (failure) {
      if (isIoFailure(failure)) this.#fenced = failure;
      throw failure;
    }
    return result;
  }

  async #acquireOwnerLock() {
    await mkdir(dirname(this.#lockPath), { recursive: true, mode: 0o700 });
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const flags =
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | noFollow;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const token = randomUUID();
      try {
        const handle = await open(this.#lockPath, flags, 0o600);
        const body = `${canonical({
          schema: "hepta.browser.journal-owner-lock.v1",
          pid: process.pid,
          createdAtMs: Date.now(),
          token,
        })}\n`;
        await handle.writeFile(body, "utf8");
        await handle.sync();
        await syncParent(this.#lockPath);
        return { handle, token };
      } catch (error) {
        if (error?.code !== "EEXIST") throw error;
        if (attempt === 0 && (await this.#removeStaleOwnerLock())) continue;
        throw ownerLockedError(
          "browser journal already has a live cross-process owner",
        );
      }
    }
    throw ownerLockedError("browser journal owner lock could not be acquired");
  }

  async #removeStaleOwnerLock() {
    let metadata;
    try {
      metadata = await lstat(this.#lockPath);
    } catch (error) {
      if (error?.code === "ENOENT") return true;
      throw error;
    }
    if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.size > MAX_LOCK_BYTES) {
      throw ownerLockedError("browser journal owner lock is malformed");
    }
    let value;
    try {
      value = JSON.parse(await readFile(this.#lockPath, "utf8"));
    } catch {
      throw ownerLockedError("browser journal owner lock is not valid JSON");
    }
    if (
      value?.schema !== "hepta.browser.journal-owner-lock.v1" ||
      !Number.isSafeInteger(value.pid) ||
      value.pid < 1 ||
      !Number.isSafeInteger(value.createdAtMs) ||
      value.createdAtMs < 1 ||
      typeof value.token !== "string"
    ) {
      throw ownerLockedError("browser journal owner lock is unsupported");
    }
    let live = true;
    try {
      process.kill(value.pid, 0);
    } catch (error) {
      if (error?.code === "ESRCH") live = false;
      else if (error?.code !== "EPERM") throw error;
    }
    if (live || Date.now() - value.createdAtMs < this.#ownerLockStaleMs) {
      return false;
    }
    await rm(this.#lockPath, { force: true });
    await syncParent(this.#lockPath);
    return true;
  }

  async #releaseOwnerLock({ handle, token }) {
    await handle.close();
    let current;
    try {
      current = JSON.parse(await readFile(this.#lockPath, "utf8"));
    } catch (error) {
      if (error?.code === "ENOENT") {
        throw new Error("browser journal owner lock disappeared before release");
      }
      throw error;
    }
    if (current?.token !== token || current?.pid !== process.pid) {
      throw ownerLockedError("browser journal owner lock changed before release");
    }
    await rm(this.#lockPath);
    await syncParent(this.#lockPath);
  }

  async #projectAndMigrate() {
    await super.listOperations("journal.projection", 1);

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
      bytes = await handle.readFile({ encoding: "utf8" });
    } finally {
      await handle.close();
    }
    if (bytes.length !== 0 && !bytes.endsWith("\n")) {
      throw new TypeError("browser journal contains an incomplete final record");
    }

    const records = new Map();
    let requiresRewrite = false;
    const lines = bytes.length === 0 ? [] : bytes.slice(0, -1).split("\n");
    for (const line of lines) {
      const envelope = requireRecord(JSON.parse(line), "browser journal envelope");
      if (envelope.schema !== SCHEMA || envelope.version !== 2) {
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
      const record = Object.freeze({ ...requireRecord(envelope.record, "journal record") });
      const key = keyOf(record);
      const folded = foldRecord(records.get(key), envelope.type, record);
      requiresRewrite ||= folded.duplicate;
      records.set(key, folded.record);
    }
    if (requiresRewrite) await this.#rewriteProjection(records);
    return records;
  }

  async #rewriteProjection(records) {
    const body = [...records.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([, record]) => {
        const unsigned = {
          schema: SCHEMA,
          version: 2,
          type: "snapshot",
          record,
        };
        return `${canonical({ ...unsigned, checksum: checksum(unsigned) })}\n`;
      })
      .join("");
    const temporary = `${this.#path}.monotonic-${process.pid}-${randomUUID()}`;
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const flags =
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | noFollow;
    const handle = await open(temporary, flags, 0o600);
    try {
      await handle.writeFile(body, "utf8");
      await handle.sync();
    } finally {
      await handle.close();
    }
    try {
      await rename(temporary, this.#path);
      await syncParent(this.#path);
    } catch (error) {
      await rm(temporary, { force: true }).catch(() => {});
      throw error;
    }
  }
}

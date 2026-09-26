import { randomUUID } from "node:crypto";
import { constants } from "node:fs";
import {
  lstat,
  mkdir,
  open,
  readFile,
  realpath,
  rename,
  rm,
} from "node:fs/promises";
import { dirname, isAbsolute, resolve } from "node:path";

const OWNER_SCHEMA = "hepta.browser.journal-owner.v1";
const RECORD_KEYS = [
  "action",
  "authorityEpoch",
  "deadlineMs",
  "destinationOrigin",
  "documentDigest",
  "effectGrantDigest",
  "finalPayloadDigest",
  "generation",
  "observationReason",
  "operationId",
  "outcomeDigest",
  "pageGeneration",
  "principalId",
  "processId",
  "profileGrantDigest",
  "profileId",
  "requestDigest",
  "semanticDigest",
  "status",
  "terminalEvidenceDigest",
  "terminalObserved",
  "verifiedUseTokenWitnessDigest",
].sort();
const IMMUTABLE_FIELDS = [
  "profileId",
  "principalId",
  "generation",
  "operationId",
  "requestDigest",
  "semanticDigest",
  "processId",
  "pageGeneration",
  "documentDigest",
  "action",
  "destinationOrigin",
  "finalPayloadDigest",
  "profileGrantDigest",
  "effectGrantDigest",
  "authorityEpoch",
  "deadlineMs",
  "verifiedUseTokenWitnessDigest",
];
const TRANSITION_FIELDS = [
  "status",
  "outcomeDigest",
  "terminalEvidenceDigest",
  "terminalObserved",
  "observationReason",
];
const MAX_OWNER_BYTES = 16_384;
const MAX_STALE_RETRIES = 3;
const IO_ERROR_CODES = new Set([
  "EACCES",
  "EBADF",
  "EBUSY",
  "EDQUOT",
  "EFBIG",
  "EIO",
  "EISDIR",
  "ELOOP",
  "EMFILE",
  "ENFILE",
  "ENOSPC",
  "ENOTDIR",
  "ENXIO",
  "EPERM",
  "EROFS",
  "ESTALE",
]);

function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

function exactRecordKeys(record) {
  const keys = Object.keys(requireRecord(record, "journal record")).sort();
  if (
    keys.length !== RECORD_KEYS.length ||
    keys.some((key, index) => key !== RECORD_KEYS[index])
  ) {
    throw new TypeError("journal record contains missing or unknown fields");
  }
}

function projection(record, fields) {
  return JSON.stringify(fields.map((field) => [field, record[field]]));
}

function assertImmutableIdentity(prior, candidate) {
  if (projection(prior, IMMUTABLE_FIELDS) !== projection(candidate, IMMUTABLE_FIELDS)) {
    throw new TypeError("journal operation identity was reused with changed semantics");
  }
}

function sameTransition(left, right) {
  return projection(left, TRANSITION_FIELDS) === projection(right, TRANSITION_FIELDS);
}

function assertDispatchTransition(record) {
  if (
    record.status !== "indeterminate" ||
    record.terminalObserved !== false ||
    record.outcomeDigest !== null ||
    record.terminalEvidenceDigest !== null
  ) {
    throw new TypeError("dispatch journal record must begin indeterminate");
  }
}

function assertObservationTransition(record) {
  if (record.status === "indeterminate") {
    if (
      record.terminalObserved !== false ||
      record.outcomeDigest !== null ||
      record.terminalEvidenceDigest !== null
    ) {
      throw new TypeError("indeterminate observation cannot claim terminal evidence");
    }
    return;
  }
  if (
    (record.status !== "succeeded" && record.status !== "failed") ||
    record.terminalObserved !== true ||
    typeof record.outcomeDigest !== "string"
  ) {
    throw new TypeError("terminal observation has an invalid state transition");
  }
}

function isDurabilityFailure(error) {
  if (error instanceof BrowserJournalOwnershipError) return false;
  if (IO_ERROR_CODES.has(error?.code)) return true;
  const message = String(error?.message ?? error ?? "");
  if (
    /checksum|malformed|incomplete|torn|owner recovery|regular file|permissions are too broad|symlink|capacity exhausted|live snapshot exceeds capacity|fenced/i.test(
      message,
    )
  ) {
    return true;
  }
  return !(error instanceof TypeError);
}

async function ensurePrivateParent(path) {
  const parent = dirname(path);
  await mkdir(parent, { recursive: true, mode: 0o700 });
  const metadata = await lstat(parent);
  if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
    throw new TypeError("browser journal owner parent must be a non-symlink directory");
  }
  if (process.platform !== "win32" && (metadata.mode & 0o077) !== 0) {
    throw new TypeError("browser journal owner parent permissions are too broad");
  }
  if ((await realpath(parent)) !== resolve(parent)) {
    throw new TypeError("browser journal owner parent path contains a symlink");
  }
}

async function syncParent(path) {
  if (process.platform === "win32") return;
  const noFollow = constants.O_NOFOLLOW ?? 0;
  const parent = await open(dirname(path), constants.O_RDONLY | noFollow);
  try {
    await parent.sync();
  } finally {
    await parent.close();
  }
}

async function linuxProcessStart(pid) {
  if (process.platform !== "linux") return null;
  try {
    const stat = await readFile(`/proc/${pid}/stat`, "utf8");
    const close = stat.lastIndexOf(")");
    if (close < 0) return null;
    const fieldsFromState = stat.slice(close + 2).trim().split(/\s+/);
    return fieldsFromState[19] ?? null;
  } catch (error) {
    if (error?.code === "ENOENT" || error?.code === "ESRCH") return null;
    throw error;
  }
}

function processExists(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    if (error?.code === "ESRCH") return false;
    if (error?.code === "EPERM") return true;
    throw error;
  }
}

function parseOwner(bytes) {
  if (Buffer.byteLength(bytes, "utf8") > MAX_OWNER_BYTES) {
    throw new TypeError("browser journal owner record exceeds byte limit");
  }
  let value;
  try {
    value = JSON.parse(bytes);
  } catch {
    throw new TypeError("browser journal owner record is malformed");
  }
  const owner = requireRecord(value, "browser journal owner record");
  const keys = Object.keys(owner).sort();
  const expected = [
    "createdAtMs",
    "ownerId",
    "pid",
    "processStart",
    "schema",
  ].sort();
  if (
    keys.length !== expected.length ||
    keys.some((key, index) => key !== expected[index]) ||
    owner.schema !== OWNER_SCHEMA ||
    typeof owner.ownerId !== "string" ||
    owner.ownerId.length < 1 ||
    owner.ownerId.length > 128 ||
    !Number.isSafeInteger(owner.pid) ||
    owner.pid < 1 ||
    !Number.isSafeInteger(owner.createdAtMs) ||
    owner.createdAtMs < 1 ||
    (owner.processStart !== null && typeof owner.processStart !== "string")
  ) {
    throw new TypeError("browser journal owner record is unsupported");
  }
  return owner;
}

async function ownerIsLive(owner) {
  if (!processExists(owner.pid)) return false;
  if (process.platform !== "linux" || owner.processStart === null) return true;
  const current = await linuxProcessStart(owner.pid);
  return current !== null && current === owner.processStart;
}

export class BrowserJournalOwnershipError extends Error {
  constructor(message) {
    super(message);
    this.name = "BrowserJournalOwnershipError";
    this.code = "BROWSER_JOURNAL_OWNED";
  }
}

export class BrowserJournalFencedError extends Error {
  constructor(message = "browser journal owner is fenced pending explicit recovery") {
    super(message);
    this.name = "BrowserJournalFencedError";
    this.code = "BROWSER_JOURNAL_FENCED";
  }
}

export class OwnedMonotonicBrowserOperationJournal {
  durable = true;

  #journal;
  #lockPath;
  #ownerId;
  #clock;
  #acquired = false;
  #acquiring = null;
  #fenced = null;
  #owner = null;

  constructor({ journal, lockPath, ownerId = randomUUID(), clock = () => Date.now() }) {
    requireRecord(journal, "journal");
    if (journal.durable !== true) {
      throw new TypeError("owned Browser journal requires a durable backing journal");
    }
    for (const method of [
      "assertProfileGenerationAvailable",
      "recordDispatch",
      "recordObservation",
      "getOperation",
      "listOperations",
      "retireProfile",
    ]) {
      if (typeof journal[method] !== "function") {
        throw new TypeError(`journal.${method} must be a function`);
      }
    }
    if (typeof lockPath !== "string" || !isAbsolute(lockPath)) {
      throw new TypeError("browser journal owner lock path must be absolute");
    }
    if (typeof ownerId !== "string" || ownerId.length < 1 || ownerId.length > 128) {
      throw new TypeError("browser journal ownerId must be a bounded string");
    }
    if (typeof clock !== "function") throw new TypeError("clock must be a function");
    this.#journal = journal;
    this.#lockPath = lockPath;
    this.#ownerId = ownerId;
    this.#clock = clock;
  }

  async acquire() {
    if (this.#acquired) return;
    if (this.#fenced) throw this.#fenced;
    if (this.#acquiring) return this.#acquiring;
    this.#acquiring = this.#acquireExclusive();
    try {
      await this.#acquiring;
      this.#acquired = true;
    } catch (error) {
      if (isDurabilityFailure(error)) {
        this.#fenced = new BrowserJournalFencedError(
          `browser journal owner acquisition failed: ${String(error?.message ?? error)}`,
        );
      }
      throw error;
    } finally {
      this.#acquiring = null;
    }
  }

  async close() {
    if (!this.#acquired || this.#owner === null) return;
    const owner = this.#owner;
    this.#acquired = false;
    this.#owner = null;
    try {
      const current = parseOwner(await readFile(this.#lockPath, "utf8"));
      if (current.ownerId !== owner.ownerId) {
        throw new BrowserJournalOwnershipError(
          "browser journal owner lock changed before release",
        );
      }
      await rm(this.#lockPath, { force: false });
      await syncParent(this.#lockPath);
    } catch (error) {
      if (error?.code === "ENOENT") return;
      this.#fenced = new BrowserJournalFencedError(
        `browser journal owner release failed: ${String(error?.message ?? error)}`,
      );
      throw error;
    }
  }

  async assertProfileGenerationAvailable(profileId, generation) {
    return this.#guard(() =>
      this.#journal.assertProfileGenerationAvailable(profileId, generation),
    );
  }

  async recordDispatch(record) {
    exactRecordKeys(record);
    assertDispatchTransition(record);
    return this.#guard(async () => {
      const prior = await this.#journal.getOperation(
        record.profileId,
        record.generation,
        record.operationId,
      );
      if (prior !== null) {
        assertImmutableIdentity(prior, record);
        return;
      }
      await this.#journal.recordDispatch(Object.freeze({ ...record }));
    });
  }

  async recordObservation(record) {
    exactRecordKeys(record);
    assertObservationTransition(record);
    return this.#guard(async () => {
      const prior = await this.#journal.getOperation(
        record.profileId,
        record.generation,
        record.operationId,
      );
      if (prior === null) {
        throw new TypeError("journal observation has no dispatch intent");
      }
      assertImmutableIdentity(prior, record);
      if (prior.terminalObserved === true) {
        if (sameTransition(prior, record)) return;
        throw new TypeError("terminal browser operation cannot change or return to indeterminate");
      }
      if (sameTransition(prior, record)) return;
      await this.#journal.recordObservation(Object.freeze({ ...record }));
    });
  }

  async getOperation(profileId, generation, operationId) {
    return this.#guard(() =>
      this.#journal.getOperation(profileId, generation, operationId),
    );
  }

  async listOperations(profileId, generation) {
    return this.#guard(() => this.#journal.listOperations(profileId, generation));
  }

  async compact() {
    return this.#guard(async () => {
      if (typeof this.#journal.compact === "function") {
        await this.#journal.compact();
      }
    });
  }

  async retireProfile(profileId, generation) {
    return this.#guard(() => this.#journal.retireProfile(profileId, generation));
  }

  async #guard(operation) {
    await this.acquire();
    if (this.#fenced) throw this.#fenced;
    try {
      return await operation();
    } catch (error) {
      if (isDurabilityFailure(error)) {
        this.#fenced = new BrowserJournalFencedError(
          `browser journal durability failure: ${String(error?.message ?? error)}`,
        );
      }
      throw error;
    }
  }

  async #acquireExclusive() {
    await ensurePrivateParent(this.#lockPath);
    const processStart = await linuxProcessStart(process.pid);
    const owner = Object.freeze({
      schema: OWNER_SCHEMA,
      ownerId: this.#ownerId,
      pid: process.pid,
      processStart,
      createdAtMs: Math.max(1, Math.trunc(this.#clock())),
    });
    const body = `${JSON.stringify(owner)}\n`;
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const flags =
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | noFollow;

    for (let attempt = 0; attempt < MAX_STALE_RETRIES; attempt += 1) {
      let handle;
      try {
        handle = await open(this.#lockPath, flags, 0o600);
      } catch (error) {
        if (error?.code !== "EEXIST") throw error;
        let existing;
        try {
          existing = parseOwner(await readFile(this.#lockPath, "utf8"));
        } catch (readError) {
          if (readError?.code === "ENOENT") continue;
          throw readError;
        }
        if (await ownerIsLive(existing)) {
          throw new BrowserJournalOwnershipError(
            `browser journal is owned by pid ${existing.pid}`,
          );
        }
        const stale = `${this.#lockPath}.stale-${process.pid}-${randomUUID()}`;
        try {
          await rename(this.#lockPath, stale);
          await syncParent(this.#lockPath);
          await rm(stale, { force: true });
        } catch (renameError) {
          if (renameError?.code === "ENOENT") continue;
          throw renameError;
        }
        continue;
      }

      try {
        await handle.writeFile(body, "utf8");
        await handle.sync();
      } finally {
        await handle.close();
      }
      await syncParent(this.#lockPath);
      this.#owner = owner;
      return;
    }
    throw new BrowserJournalOwnershipError(
      "browser journal owner lock could not be acquired after stale-owner recovery",
    );
  }
}

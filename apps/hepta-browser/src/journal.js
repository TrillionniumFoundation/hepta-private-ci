import { createHash, randomUUID } from "node:crypto";
import { hostname } from "node:os";
import { constants } from "node:fs";
import {
  lstat,
  mkdir,
  open,
  realpath,
  rename,
  rm,
} from "node:fs/promises";
import { dirname, isAbsolute, resolve } from "node:path";

const SCHEMA = "hepta.browser.operation-journal.v2";
const LEGACY_SCHEMA = "hepta.browser.operation-journal.v1";
const RETIRED_SCHEMA = "hepta.browser.retired-profile-generations.v1";
const MAX_LINE_BYTES = 262_144;
const MAX_RETIRED_BYTES = 8 * 1024 * 1024;
const MAX_RETIRED_PROFILES = 65_536;
const MAX_LIVE_RECORDS = 65_536;
const MAX_FILE_BYTES = 64 * 1024 * 1024;
const COMPACT_AT_BYTES = 48 * 1024 * 1024;
const LOCK_WAIT_MS = 5_000;
const LOCK_RETRY_MS = 10;
const UTF8 = new TextEncoder();
const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);
const STATUS = new Set(["indeterminate", "succeeded", "failed"]);
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

// Outcomes may advance; every other stored field is immutable even when a
// caller repeats a valid request/semantic digest while substituting metadata.
const OBSERVATION_KEYS = new Set([
  "observationReason", "outcomeDigest", "status", "terminalEvidenceDigest", "terminalObserved",
]);
const IMMUTABLE_RECORD_KEYS = RECORD_KEYS.filter((key) => !OBSERVATION_KEYS.has(key));

class JournalSemanticError extends TypeError {}
class JournalBusyError extends Error {}

function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

function exactKeys(value, expected, name) {
  const actual = Object.keys(value).sort();
  if (
    actual.length !== expected.length ||
    actual.some((key, index) => key !== expected[index])
  ) {
    throw new TypeError(`${name} contains missing or unknown fields`);
  }
}

function stableId(value, name) {
  if (typeof value !== "string" || !STABLE_ID.test(value)) {
    throw new TypeError(`${name} must be a bounded stable identifier`);
  }
  return value;
}

function positiveInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

function nonNegativeInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new TypeError(`${name} must be a non-negative safe integer`);
  }
  return value;
}

function digest(value, name, { nullable = false } = {}) {
  if (nullable && value === null) return null;
  if (
    typeof value !== "string" ||
    !DIGEST.test(value) ||
    value === ZERO_DIGEST
  ) {
    throw new TypeError(`${name} must be a non-zero lowercase SHA-256 digest`);
  }
  return value;
}

function matchesWeb(url) {
  return url.protocol === "http:" || url.protocol === "https:";
}

function canonicalOrigin(value) {
  if (typeof value !== "string") {
    throw new TypeError("destinationOrigin must be a string");
  }
  const url = new URL(value);
  if (
    !matchesWeb(url) ||
    url.origin !== value ||
    url.pathname !== "/" ||
    url.search ||
    url.hash
  ) {
    throw new TypeError("destinationOrigin must be a canonical HTTP(S) origin");
  }
  return value;
}

function boundedReason(value) {
  if (
    typeof value !== "string" ||
    value.length < 1 ||
    UTF8.encode(value).byteLength > 256
  ) {
    throw new TypeError("observationReason must be a bounded string");
  }
  return value;
}

function normalizedRecord(record) {
  return Object.freeze(
    Object.fromEntries(RECORD_KEYS.map((key) => [key, record[key]])),
  );
}

function validateDurableRecord(value, type) {
  const record = requireRecord(value, "journal record");
  exactKeys(record, RECORD_KEYS, "journal record");
  stableId(record.profileId, "profileId");
  stableId(record.principalId, "principalId");
  positiveInteger(record.generation, "generation");
  stableId(record.operationId, "operationId");
  digest(record.requestDigest, "requestDigest");
  digest(record.semanticDigest, "semanticDigest");
  stableId(record.processId, "processId");
  nonNegativeInteger(record.pageGeneration, "pageGeneration");
  digest(record.documentDigest, "documentDigest", { nullable: true });
  stableId(record.action, "action");
  canonicalOrigin(record.destinationOrigin);
  digest(record.finalPayloadDigest, "finalPayloadDigest");
  digest(record.profileGrantDigest, "profileGrantDigest");
  digest(record.effectGrantDigest, "effectGrantDigest");
  positiveInteger(record.authorityEpoch, "authorityEpoch");
  positiveInteger(record.deadlineMs, "deadlineMs");
  digest(
    record.verifiedUseTokenWitnessDigest,
    "verifiedUseTokenWitnessDigest",
  );
  if (!STATUS.has(record.status)) {
    throw new TypeError("journal status is not registered");
  }
  boundedReason(record.observationReason);
  const terminalEvidenceDigest = digest(
    record.terminalEvidenceDigest,
    "terminalEvidenceDigest",
    { nullable: true },
  );
  if (record.status === "indeterminate") {
    if (
      record.terminalObserved !== false ||
      record.outcomeDigest !== null ||
      terminalEvidenceDigest !== null
    ) {
      throw new TypeError(
        "indeterminate journal record cannot claim a terminal outcome or evidence",
      );
    }
  } else {
    if (record.terminalObserved !== true) {
      throw new TypeError("terminal journal status requires terminalObserved=true");
    }
    digest(record.outcomeDigest, "outcomeDigest");
    if (
      record.observationReason === "authenticated_persisted_receipt" &&
      terminalEvidenceDigest === null
    ) {
      throw new TypeError(
        "authenticated persisted terminal observation requires evidence digest",
      );
    }
  }
  if (type === "dispatch" && record.status !== "indeterminate") {
    throw new TypeError("dispatch journal record must begin indeterminate");
  }
  return normalizedRecord(record);
}

function migrateLegacyRecord(value, type) {
  const record = requireRecord(value, "legacy journal record");
  if (Object.prototype.hasOwnProperty.call(record, "terminalEvidenceDigest")) {
    return validateDurableRecord(record, type);
  }
  return validateDurableRecord(
    { ...record, terminalEvidenceDigest: null },
    type,
  );
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

function profilePrefix(profileId, generation) {
  return `${profileId}\u0000${generation}\u0000`;
}

function sameRecord(left, right) {
  return canonical(left) === canonical(right);
}

function assertSameSemantics(prior, next, message) {
  if (IMMUTABLE_RECORD_KEYS.some((key) => prior[key] !== next[key])) {
    throw new JournalSemanticError(message);
  }
}

function applyTransition(records, type, record) {
  const key = keyOf(record);
  const prior = records.get(key);

  if (type === "dispatch") {
    if (!prior) {
      if (records.size >= MAX_LIVE_RECORDS) {
        throw new JournalSemanticError(
          "browser journal live index capacity exhausted",
        );
      }
      records.set(key, record);
      return true;
    }
    assertSameSemantics(
      prior,
      record,
      "journal operation identity was reused with changed semantics",
    );
    // A dispatch retry is always a no-op once the immutable identity exists.
    // In particular it cannot erase a later indeterminate observation or a
    // terminal tombstone.
    return false;
  }

  if (type === "observation") {
    if (!prior) {
      throw new JournalSemanticError("journal observation has no dispatch intent");
    }
    assertSameSemantics(
      prior,
      record,
      "journal observation changed immutable semantics",
    );
    if (sameRecord(prior, record)) return false;
    if (prior.terminalObserved === true) {
      throw new JournalSemanticError(
        "terminal browser operation cannot change or return to indeterminate",
      );
    }
    records.set(key, record);
    return true;
  }

  if (type === "snapshot") {
    if (!prior) {
      if (records.size >= MAX_LIVE_RECORDS) {
        throw new JournalSemanticError(
          "browser journal live index capacity exhausted",
        );
      }
      records.set(key, record);
      return true;
    }
    assertSameSemantics(
      prior,
      record,
      "browser journal snapshot conflicts with prior semantics",
    );
    if (sameRecord(prior, record)) return false;
    if (prior.terminalObserved === true) {
      throw new JournalSemanticError(
        "browser journal snapshot conflicts with terminal state",
      );
    }
    records.set(key, record);
    return true;
  }

  throw new TypeError("browser journal record type is unsupported");
}

function assertGenerationHistoryClear(records, profileId, generation) {
  stableId(profileId, "profileId");
  positiveInteger(generation, "generation");
  const sameGenerationPrefix = profilePrefix(profileId, generation);
  const profileIdPrefix = `${profileId}\u0000`;
  let sameGenerationHistory = false;
  let unresolvedOtherGeneration = false;
  for (const [key, record] of records) {
    if (!key.startsWith(profileIdPrefix)) continue;
    if (key.startsWith(sameGenerationPrefix)) {
      sameGenerationHistory = true;
      continue;
    }
    if (record.terminalObserved !== true) unresolvedOtherGeneration = true;
  }
  if (sameGenerationHistory) {
    throw new JournalSemanticError(
      "profile generation has durable operation history and cannot be reopened",
    );
  }
  if (unresolvedOtherGeneration) {
    throw new JournalSemanticError(
      "profile has unresolved durable effects from another generation",
    );
  }
}

function assertGenerationAvailable(retired, profileId, generation) {
  stableId(profileId, "profileId");
  positiveInteger(generation, "generation");
  const highWater = retired.get(profileId);
  if (highWater !== undefined && generation <= highWater) {
    throw new JournalSemanticError("profile generation has already been retired");
  }
}

function assertRetirable(records, profileId, generation) {
  const prefix = profilePrefix(profileId, generation);
  for (const [key, record] of records) {
    if (key.startsWith(prefix) && record.terminalObserved !== true) {
      throw new JournalSemanticError(
        "profile generation has unresolved browser effects and cannot be retired",
      );
    }
  }
}

async function syncDirectory(path) {
  const noFollow = constants.O_NOFOLLOW ?? 0;
  const handle = await open(path, constants.O_RDONLY | noFollow);
  try {
    const info = await handle.stat();
    if (!info.isDirectory()) {
      throw new TypeError("browser journal durability barrier is not a directory");
    }
    await handle.sync();
  } finally {
    await handle.close();
  }
}

async function ensureCanonicalPrivateParent(path) {
  const parent = resolve(dirname(path));
  const missing = [];
  let cursor = parent;
  while (true) {
    try {
      const metadata = await lstat(cursor);
      if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
        throw new TypeError(
          "browser journal parent must be a regular non-symlink directory",
        );
      }
      break;
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
      const next = dirname(cursor);
      if (next === cursor) throw error;
      missing.push(cursor);
      cursor = next;
    }
  }

  for (const directory of missing.reverse()) {
    await mkdir(directory, { mode: 0o700 });
    await syncDirectory(dirname(directory));
  }

  const metadata = await lstat(parent);
  if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
    throw new TypeError(
      "browser journal parent must be a regular non-symlink directory",
    );
  }
  if (process.platform !== "win32" && (metadata.mode & 0o077) !== 0) {
    throw new TypeError("browser journal parent directory permissions are too broad");
  }
  const actual = await realpath(parent);
  if (actual !== parent) {
    throw new TypeError("browser journal parent path contains a symlink");
  }
}

function envelopeLine(type, record) {
  const validated = validateDurableRecord(
    record,
    type === "snapshot" ? "snapshot" : type,
  );
  const unsigned = { schema: SCHEMA, version: 2, type, record: validated };
  const line = `${canonical({ ...unsigned, checksum: checksum(unsigned) })}\n`;
  if (UTF8.encode(line).byteLength > MAX_LINE_BYTES) {
    throw new TypeError("browser journal record exceeds line limit");
  }
  return line;
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function processIsAlive(pid) {
  if (!Number.isSafeInteger(pid) || pid < 1) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    if (error?.code === "ESRCH") return false;
    return true;
  }
}

export class MemoryBrowserOperationJournal {
  durable = false;
  #records = new Map();
  #retired = new Map();

  async assertProfileGenerationAvailable(profileId, generation) {
    assertGenerationAvailable(this.#retired, profileId, generation);
    assertGenerationHistoryClear(this.#records, profileId, generation);
  }

  async recordDispatch(record) {
    const snapshot = validateDurableRecord(record, "dispatch");
    assertGenerationAvailable(this.#retired, snapshot.profileId, snapshot.generation);
    applyTransition(this.#records, "dispatch", snapshot);
  }

  async recordObservation(record) {
    const snapshot = validateDurableRecord(record, "observation");
    applyTransition(this.#records, "observation", snapshot);
  }

  async getOperation(profileId, generation, operationId) {
    return (
      this.#records.get(`${profileId}\u0000${generation}\u0000${operationId}`) ??
      null
    );
  }

  async listOperations(profileId, generation) {
    const prefix = profilePrefix(profileId, generation);
    return [...this.#records.entries()]
      .filter(([key]) => key.startsWith(prefix))
      .map(([, value]) => value);
  }

  async retireProfile(profileId, generation) {
    stableId(profileId, "profileId");
    positiveInteger(generation, "generation");
    assertRetirable(this.#records, profileId, generation);
    const prior = this.#retired.get(profileId) ?? 0;
    if (generation > prior) this.#retired.set(profileId, generation);
    const prefix = profilePrefix(profileId, generation);
    for (const key of [...this.#records.keys()]) {
      if (key.startsWith(prefix)) this.#records.delete(key);
    }
  }
}

export class FileBrowserOperationJournal {
  durable = true;
  #path;
  #retiredPath;
  #lockPath;
  #tail = Promise.resolve();
  #rewriteCounter = 0;
  #faultInjector;
  #fencedCause = null;
  #instanceToken = randomUUID();

  constructor(path, { faultInjector = null } = {}) {
    if (typeof path !== "string" || !isAbsolute(path)) {
      throw new TypeError("browser journal path must be absolute");
    }
    if (faultInjector !== null && typeof faultInjector !== "function") {
      throw new TypeError("browser journal faultInjector must be a function or null");
    }
    this.#path = path;
    this.#retiredPath = `${path}.retired`;
    this.#lockPath = `${path}.owner-lock`;
    this.#faultInjector = faultInjector;
  }

  async assertProfileGenerationAvailable(profileId, generation) {
    stableId(profileId, "profileId");
    positiveInteger(generation, "generation");
    return this.#serialize(async () => {
      const retired = await this.#loadRetired();
      assertGenerationAvailable(retired, profileId, generation);
      const records = await this.#load();
      assertGenerationHistoryClear(records, profileId, generation);
    });
  }

  async recordDispatch(record) {
    const snapshot = validateDurableRecord(record, "dispatch");
    return this.#serialize(async () => {
      // Check retirement under the same interprocess writer lock as append.
      const retired = await this.#loadRetired();
      assertGenerationAvailable(retired, snapshot.profileId, snapshot.generation);
      const records = await this.#load();
      if (!applyTransition(records, "dispatch", snapshot)) return;
      const size = await this.#append({ type: "dispatch", record: snapshot });
      if (size >= COMPACT_AT_BYTES) await this.#rewrite(records);
    });
  }

  async recordObservation(record) {
    const snapshot = validateDurableRecord(record, "observation");
    return this.#serialize(async () => {
      const records = await this.#load();
      if (!applyTransition(records, "observation", snapshot)) return;
      const size = await this.#append({ type: "observation", record: snapshot });
      if (size >= COMPACT_AT_BYTES) await this.#rewrite(records);
    });
  }

  async getOperation(profileId, generation, operationId) {
    stableId(profileId, "profileId");
    positiveInteger(generation, "generation");
    stableId(operationId, "operationId");
    return this.#serialize(async () => {
      const records = await this.#load();
      return (
        records.get(`${profileId}\u0000${generation}\u0000${operationId}`) ??
        null
      );
    });
  }

  async listOperations(profileId, generation) {
    stableId(profileId, "profileId");
    positiveInteger(generation, "generation");
    return this.#serialize(async () => {
      const records = await this.#load();
      const prefix = profilePrefix(profileId, generation);
      return [...records.entries()]
        .filter(([key]) => key.startsWith(prefix))
        .map(([, value]) => value);
    });
  }

  async compact() {
    return this.#serialize(async () => {
      const records = await this.#load();
      await this.#rewrite(records);
    });
  }

  async retireProfile(profileId, generation) {
    stableId(profileId, "profileId");
    positiveInteger(generation, "generation");
    return this.#serialize(async () => {
      const records = await this.#load();
      assertRetirable(records, profileId, generation);

      // Persist the non-resurrection fence first. A crash can therefore leave
      // redundant terminal records, but cannot make the retired generation
      // admissible again.
      const retired = await this.#loadRetired();
      const prior = retired.get(profileId) ?? 0;
      if (generation > prior) {
        if (!retired.has(profileId) && retired.size >= MAX_RETIRED_PROFILES) {
          throw new JournalSemanticError(
            "retired profile generation capacity is exhausted",
          );
        }
        retired.set(profileId, generation);
        await this.#rewriteRetired(retired);
        this.#fault("retired_high_water_committed_before_journal_rewrite");
      }

      const prefix = profilePrefix(profileId, generation);
      for (const key of [...records.keys()]) {
        if (key.startsWith(prefix)) records.delete(key);
      }
      await this.#rewrite(records);
    });
  }

  #assertNotFenced() {
    if (this.#fencedCause === null) return;
    const error = new Error(
      `browser journal owner requires recovery after durability failure: ${String(
        this.#fencedCause?.message ?? this.#fencedCause,
      )}`,
    );
    error.name = "BrowserJournalOwnerFencedError";
    error.code = "BROWSER_JOURNAL_OWNER_FENCED";
    throw error;
  }

  #fence(error) {
    this.#fencedCause ??= error;
  }

  async #serialize(operation) {
    const run = this.#tail.catch(() => {}).then(async () => {
      this.#assertNotFenced();
      let release = null;
      try {
        release = await this.#acquireOwnerLock();
        const result = await operation();
        await release();
        release = null;
        return result;
      } catch (error) {
        if (release !== null) {
          try {
            await release();
          } catch (releaseError) {
            this.#fence(releaseError);
          }
        }
        if (
          !(error instanceof JournalSemanticError) &&
          !(error instanceof JournalBusyError)
        ) {
          this.#fence(error);
        }
        throw error;
      }
    });
    this.#tail = run.catch(() => {});
    return run;
  }

  async #acquireOwnerLock() {
    await ensureCanonicalPrivateParent(this.#path);
    const startedAt = Date.now();
    const owner = {
      schema: "hepta.browser.journal-owner-lock.v1",
      pid: process.pid,
      hostname: hostname(),
      token: this.#instanceToken,
      path: this.#path,
      createdAtMs: startedAt,
    };
    const body = `${canonical(owner)}\n`;
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const flags =
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | noFollow;

    while (true) {
      let handle;
      let created = false;
      try {
        handle = await open(this.#lockPath, flags, 0o600);
        created = true;
        try {
          await handle.writeFile(body, "utf8");
        } finally {
          await handle.close();
        }
        let released = false;
        return async () => {
          if (released) return;
          const current = await this.#readOwnerLock();
          if (
            current?.token !== this.#instanceToken ||
            current?.pid !== process.pid
          ) {
            throw new Error(
              "browser journal owner lock identity changed before release",
            );
          }
          released = true;
          await rm(this.#lockPath, { force: false });
        };
      } catch (error) {
        await handle?.close().catch(() => {});
        if (error?.code !== "EEXIST") {
          if (created) {
            await rm(this.#lockPath, { force: true }).catch(() => {});
          }
          throw error;
        }
        if (await this.#breakStaleOwnerLock()) continue;
        if (Date.now() - startedAt >= LOCK_WAIT_MS) {
          throw new JournalBusyError(
            "browser journal is owned by another live process",
          );
        }
        await delay(LOCK_RETRY_MS);
      }
    }
  }

  async #readOwnerLock() {
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const before = await lstat(this.#lockPath);
    if (!before.isFile() || before.isSymbolicLink()) {
      throw new TypeError("browser journal owner lock is not a regular file");
    }
    const handle = await open(this.#lockPath, constants.O_RDONLY | noFollow);
    try {
      const opened = await handle.stat();
      const body = await handle.readFile({ encoding: "utf8" });
      const after = await lstat(this.#lockPath);
      if (
        opened.dev !== before.dev ||
        opened.ino !== before.ino ||
        opened.dev !== after.dev ||
        opened.ino !== after.ino
      ) {
        throw new Error("browser journal owner lock changed during verification");
      }
      return JSON.parse(body);
    } finally {
      await handle.close();
    }
  }

  async #breakStaleOwnerLock() {
    let metadata;
    try {
      metadata = await lstat(this.#lockPath);
    } catch (error) {
      if (error?.code === "ENOENT") return true;
      throw error;
    }
    if (!metadata.isFile() || metadata.isSymbolicLink()) {
      throw new TypeError("browser journal owner lock is not a regular file");
    }

    let owner;
    try {
      owner = await this.#readOwnerLock();
    } catch {
      // A peer can observe the lock between O_EXCL creation and metadata write.
      // Treat a young incomplete lock as live; an old one is recoverable.
      if (Date.now() - metadata.mtimeMs < LOCK_WAIT_MS) return false;
      owner = null;
    }
    if (owner !== null) {
      if (
        owner?.schema !== "hepta.browser.journal-owner-lock.v1" ||
        owner?.hostname !== hostname() ||
        !Number.isSafeInteger(owner?.pid)
      ) {
        return false;
      }
      if (processIsAlive(owner.pid)) return false;
    }

    const stale = `${this.#lockPath}.stale-${process.pid}-${randomUUID()}`;
    try {
      await rename(this.#lockPath, stale);
    } catch (error) {
      if (error?.code === "ENOENT") return true;
      throw error;
    }
    await rm(stale, { force: true });
    return true;
  }

  async #loadRetired() {
    await ensureCanonicalPrivateParent(this.#retiredPath);
    const noFollow = constants.O_NOFOLLOW ?? 0;
    let handle;
    try {
      handle = await open(this.#retiredPath, constants.O_RDONLY | noFollow);
    } catch (error) {
      if (error?.code === "ENOENT") return new Map();
      throw error;
    }

    let bytes;
    try {
      const info = await handle.stat();
      if (!info.isFile() || info.size > MAX_RETIRED_BYTES) {
        throw new TypeError(
          "retired profile generation ledger is not a bounded regular file",
        );
      }
      if (process.platform !== "win32" && (info.mode & 0o077) !== 0) {
        throw new TypeError(
          "retired profile generation ledger permissions are too broad",
        );
      }
      bytes = await handle.readFile({ encoding: "utf8" });
    } finally {
      await handle.close();
    }

    let envelope;
    try {
      envelope = JSON.parse(bytes);
    } catch {
      throw new TypeError("retired profile generation ledger is malformed");
    }
    const object = requireRecord(envelope, "retired profile generation ledger");
    exactKeys(
      object,
      ["checksum", "profiles", "schema", "version"].sort(),
      "retired profile generation ledger",
    );
    if (
      object.schema !== RETIRED_SCHEMA ||
      object.version !== 1 ||
      typeof object.checksum !== "string" ||
      !DIGEST.test(object.checksum)
    ) {
      throw new TypeError("retired profile generation ledger is unsupported");
    }
    const profiles = requireRecord(
      object.profiles,
      "retired profile generation profiles",
    );
    const profileIds = Object.keys(profiles);
    if (profileIds.length > MAX_RETIRED_PROFILES) {
      throw new TypeError("retired profile generation ledger exceeds capacity");
    }
    // JSON object enumeration places integer-index names first. Match the
    // writer's code-unit sorting plus that specified enumeration order.
    const sorted = Object.keys(
      Object.fromEntries([...profileIds].sort().map((profileId) => [profileId, null])),
    );
    if (profileIds.some((profileId, index) => profileId !== sorted[index])) {
      throw new TypeError("retired profile generation ledger is not canonical");
    }
    const retired = new Map();
    for (const profileId of profileIds) {
      stableId(profileId, "retired profileId");
      retired.set(
        profileId,
        positiveInteger(profiles[profileId], "retired generation"),
      );
    }
    const unsigned = {
      schema: object.schema,
      version: object.version,
      profiles: object.profiles,
    };
    if (checksum(unsigned) !== object.checksum) {
      throw new TypeError("retired profile generation checksum mismatch");
    }
    const expected = `${canonical({
      ...unsigned,
      checksum: checksum(unsigned),
    })}\n`;
    if (bytes !== expected) {
      throw new TypeError("retired profile generation ledger is not canonical");
    }
    return retired;
  }

  async #rewriteRetired(retired) {
    if (!(retired instanceof Map)) {
      throw new TypeError("retired profile generation state must be a Map");
    }
    if (retired.size > MAX_RETIRED_PROFILES) {
      throw new JournalSemanticError(
        "retired profile generation ledger exceeds capacity",
      );
    }
    const profiles = Object.fromEntries(
      [...retired.entries()]
        .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
        .map(([profileId, generation]) => {
          stableId(profileId, "retired profileId");
          return [profileId, positiveInteger(generation, "retired generation")];
        }),
    );
    const unsigned = {
      schema: RETIRED_SCHEMA,
      version: 1,
      profiles,
    };
    const body = `${canonical({
      ...unsigned,
      checksum: checksum(unsigned),
    })}\n`;
    if (UTF8.encode(body).byteLength > MAX_RETIRED_BYTES) {
      throw new JournalSemanticError(
        "retired profile generation ledger exceeds byte limit",
      );
    }

    await ensureCanonicalPrivateParent(this.#retiredPath);
    const temporary = `${this.#retiredPath}.tmp-${process.pid}-${this.#rewriteCounter++}`;
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const flags =
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | noFollow;
    const handle = await open(temporary, flags, 0o600);
    try {
      await handle.writeFile(body, "utf8");
      await handle.sync();
      this.#fault("retired_temp_fsynced_before_rename");
    } finally {
      await handle.close();
    }
    try {
      await rename(temporary, this.#retiredPath);
      this.#fault("retired_renamed_before_parent_fsync");
      await syncDirectory(dirname(this.#retiredPath));
    } catch (error) {
      await rm(temporary, { force: true }).catch(() => {});
      throw error;
    }
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
    let needsRewrite = false;
    const terminated = bytes.length === 0 || bytes.endsWith("\n");
    const lines = bytes.length === 0 ? [] : bytes.split("\n");
    if (lines.at(-1) === "") lines.pop();
    for (const [index, line] of lines.entries()) {
      if (!terminated && index === lines.length - 1) {
        // Every acknowledged append includes and fsyncs its final newline.
        // An unterminated final line is therefore never authoritative, even
        // when its JSON happens to be syntactically complete.
        needsRewrite = true;
        break;
      }
      if (line.length === 0 || UTF8.encode(line).byteLength > MAX_LINE_BYTES) {
        throw new TypeError("browser journal line exceeds limit");
      }
      let object;
      try {
        object = requireRecord(JSON.parse(line), "browser journal envelope");
      } catch {
        throw new TypeError("browser journal contains malformed JSON");
      }
      exactKeys(
        object,
        ["checksum", "record", "schema", "type", "version"].sort(),
        "browser journal envelope",
      );
      if (!matchesRecordType(object.type)) {
        throw new TypeError("browser journal record type is unsupported");
      }
      const unsigned = {
        schema: object.schema,
        version: object.version,
        type: object.type,
        record: object.record,
      };
      if (
        typeof object.checksum !== "string" ||
        checksum(unsigned) !== object.checksum
      ) {
        throw new TypeError("browser journal checksum mismatch");
      }

      let record;
      if (object.schema === SCHEMA && object.version === 2) {
        record = validateDurableRecord(
          object.record,
          object.type === "snapshot" ? "snapshot" : object.type,
        );
      } else if (object.schema === LEGACY_SCHEMA && object.version === 1) {
        record = migrateLegacyRecord(
          object.record,
          object.type === "snapshot" ? "snapshot" : object.type,
        );
        needsRewrite = true;
      } else {
        throw new TypeError("browser journal envelope is unsupported");
      }
      applyTransition(records, object.type, record);
    }

    if (needsRewrite) {
      await this.#rewrite(records);
      this.#fault("torn_prefix_repaired");
    }
    return records;
  }

  async #append({ type, record }, allowCompact = true) {
    const line = envelopeLine(type, record);
    const lineBytes = UTF8.encode(line).byteLength;
    await ensureCanonicalPrivateParent(this.#path);
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const createFlags =
      constants.O_WRONLY |
      constants.O_APPEND |
      constants.O_CREAT |
      constants.O_EXCL |
      noFollow;
    const appendFlags = constants.O_WRONLY | constants.O_APPEND | noFollow;
    let handle;
    let created = false;
    try {
      try {
        handle = await open(this.#path, createFlags, 0o600);
        created = true;
      } catch (error) {
        if (error?.code !== "EEXIST") throw error;
        handle = await open(this.#path, appendFlags);
      }
      const info = await handle.stat();
      if (!info.isFile()) {
        throw new TypeError("browser journal is not a regular file");
      }
      if (process.platform !== "win32" && (info.mode & 0o077) !== 0) {
        throw new TypeError("browser journal permissions are too broad");
      }
      if (info.size + lineBytes > MAX_FILE_BYTES) {
        if (!allowCompact) {
          throw new JournalSemanticError(
            "browser journal capacity exhausted after compaction",
          );
        }
        await handle.close();
        handle = null;
        const records = await this.#load();
        await this.#rewrite(records);
        return this.#append({ type, record }, false);
      }
      await handle.writeFile(line, "utf8");
      await handle.sync();
      if (created) {
        this.#fault("append_created_fsynced_before_parent_fsync");
      }
      await syncDirectory(dirname(this.#path));
      return info.size + lineBytes;
    } finally {
      await handle?.close();
    }
  }

  async #rewrite(records) {
    await ensureCanonicalPrivateParent(this.#path);
    const body = [...records.entries()]
      .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
      .map(([, record]) => envelopeLine("snapshot", record))
      .join("");
    const bytes = UTF8.encode(body);
    if (bytes.byteLength > MAX_FILE_BYTES) {
      throw new JournalSemanticError(
        "browser journal live snapshot exceeds capacity; rotate the profile generation",
      );
    }
    const temporary = `${this.#path}.compact-${process.pid}-${this.#rewriteCounter++}`;
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const flags =
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | noFollow;
    const handle = await open(temporary, flags, 0o600);
    try {
      await handle.writeFile(body, "utf8");
      await handle.sync();
      this.#fault("compact_temp_fsynced_before_rename");
    } finally {
      await handle.close();
    }
    try {
      await rename(temporary, this.#path);
      this.#fault("compact_renamed_before_parent_fsync");
      await syncDirectory(dirname(this.#path));
    } catch (error) {
      await rm(temporary, { force: true }).catch(() => {});
      throw error;
    }
  }

  #fault(name) {
    this.#faultInjector?.(name);
  }
}

function matchesRecordType(value) {
  return value === "dispatch" || value === "observation" || value === "snapshot";
}

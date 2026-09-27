import { createHash, randomUUID } from "node:crypto";
import { constants } from "node:fs";
import {
  mkdir,
  open,
  readFile,
  realpath,
  rename,
  rm,
  stat,
  truncate,
  writeFile,
} from "node:fs/promises";
import { dirname, isAbsolute, join, resolve } from "node:path";

const SCHEMA = "hepta.browser.operation-journal.v2";
const RECORD_VERSION = 2;
const GENERATION_SCHEMA = "hepta.browser.profile-generation-retirement.v1";
const GENERATION_VERSION = 1;
const MAX_LINE_BYTES = 262_144;
const DEFAULT_MAX_FILE_BYTES = 64 * 1024 * 1024;
const DEFAULT_COMPACT_AT_BYTES = 48 * 1024 * 1024;
const MAX_RECORDS = 65_536;
const LOCK_TIMEOUT_MS = 5_000;
const LOCK_RETRY_MS = 20;
const OWNERLESS_LOCK_STALE_MS = 30_000;
const UTF8 = new TextEncoder();
const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);

const RECORD_KEYS = Object.freeze([
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
]);
const MUTABLE_RECORD_KEYS = new Set([
  "observationReason",
  "outcomeDigest",
  "status",
  "terminalEvidenceDigest",
  "terminalObserved",
]);
const IMMUTABLE_RECORD_KEYS = Object.freeze(
  RECORD_KEYS.filter((key) => !MUTABLE_RECORD_KEYS.has(key)),
);
const ENVELOPE_KEYS = Object.freeze([
  "checksum",
  "record",
  "schema",
  "type",
  "version",
]);
const GENERATION_KEYS = Object.freeze(["generation", "profileId"]);

class BrowserJournalSemanticError extends TypeError {
  constructor(message) {
    super(message);
    this.name = "BrowserJournalSemanticError";
  }
}

class BrowserJournalCapacityError extends BrowserJournalSemanticError {
  constructor(message) {
    super(message);
    this.name = "BrowserJournalCapacityError";
  }
}

function requireRecord(value, name) {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    Object.getPrototypeOf(value) !== Object.prototype
  ) {
    throw new BrowserJournalSemanticError(`${name} must be a plain object`);
  }
  return value;
}

function exactKeys(value, expected, name) {
  const keys = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (
    keys.length !== wanted.length ||
    keys.some((key, index) => key !== wanted[index])
  ) {
    throw new BrowserJournalSemanticError(
      `${name} contains missing or unknown fields`,
    );
  }
}

function stableId(value, name) {
  if (typeof value !== "string" || !STABLE_ID.test(value)) {
    throw new BrowserJournalSemanticError(
      `${name} must be a bounded stable identifier`,
    );
  }
  return value;
}

function sha256Digest(value, name, { nullable = false } = {}) {
  if (nullable && value === null) return null;
  if (
    typeof value !== "string" ||
    !DIGEST.test(value) ||
    value === ZERO_DIGEST
  ) {
    throw new BrowserJournalSemanticError(
      `${name} must be a non-zero lowercase SHA-256 digest`,
    );
  }
  return value;
}

function positiveInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new BrowserJournalSemanticError(
      `${name} must be a positive safe integer`,
    );
  }
  return value;
}

function nonNegativeInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new BrowserJournalSemanticError(
      `${name} must be a non-negative safe integer`,
    );
  }
  return value;
}

function boundedString(value, name, maximumBytes) {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    UTF8.encode(value).byteLength > maximumBytes
  ) {
    throw new BrowserJournalSemanticError(
      `${name} must be a non-empty bounded string`,
    );
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

function validateDurableRecord(value, recordType) {
  const record = requireRecord(value, `${recordType} record`);
  exactKeys(record, RECORD_KEYS, `${recordType} record`);
  const terminalObserved = record.terminalObserved;
  if (typeof terminalObserved !== "boolean") {
    throw new BrowserJournalSemanticError(
      `${recordType} record terminalObserved must be boolean`,
    );
  }
  const snapshot = {
    profileId: stableId(record.profileId, "record.profileId"),
    principalId: stableId(record.principalId, "record.principalId"),
    generation: positiveInteger(record.generation, "record.generation"),
    operationId: stableId(record.operationId, "record.operationId"),
    requestDigest: sha256Digest(record.requestDigest, "record.requestDigest"),
    semanticDigest: sha256Digest(
      record.semanticDigest,
      "record.semanticDigest",
    ),
    processId: stableId(record.processId, "record.processId"),
    pageGeneration: nonNegativeInteger(
      record.pageGeneration,
      "record.pageGeneration",
    ),
    documentDigest: sha256Digest(
      record.documentDigest,
      "record.documentDigest",
      { nullable: true },
    ),
    action: stableId(record.action, "record.action"),
    destinationOrigin: boundedString(
      record.destinationOrigin,
      "record.destinationOrigin",
      4096,
    ),
    finalPayloadDigest: sha256Digest(
      record.finalPayloadDigest,
      "record.finalPayloadDigest",
    ),
    profileGrantDigest: sha256Digest(
      record.profileGrantDigest,
      "record.profileGrantDigest",
    ),
    effectGrantDigest: sha256Digest(
      record.effectGrantDigest,
      "record.effectGrantDigest",
    ),
    authorityEpoch: positiveInteger(
      record.authorityEpoch,
      "record.authorityEpoch",
    ),
    deadlineMs: positiveInteger(record.deadlineMs, "record.deadlineMs"),
    verifiedUseTokenWitnessDigest: sha256Digest(
      record.verifiedUseTokenWitnessDigest,
      "record.verifiedUseTokenWitnessDigest",
    ),
    status: record.status,
    outcomeDigest: record.outcomeDigest,
    terminalEvidenceDigest: record.terminalEvidenceDigest,
    terminalObserved,
    observationReason: boundedString(
      record.observationReason,
      "record.observationReason",
      512,
    ),
  };

  if (recordType === "dispatch") {
    if (
      terminalObserved ||
      snapshot.status !== "indeterminate" ||
      snapshot.outcomeDigest !== null ||
      snapshot.terminalEvidenceDigest !== null ||
      snapshot.observationReason !== "dispatching"
    ) {
      throw new BrowserJournalSemanticError(
        "dispatch record must be the initial indeterminate dispatching state",
      );
    }
  } else if (terminalObserved) {
    if (snapshot.status !== "succeeded" && snapshot.status !== "failed") {
      throw new BrowserJournalSemanticError(
        `${recordType} terminal status is not registered`,
      );
    }
    snapshot.outcomeDigest = sha256Digest(
      snapshot.outcomeDigest,
      "record.outcomeDigest",
    );
    snapshot.terminalEvidenceDigest = sha256Digest(
      snapshot.terminalEvidenceDigest,
      "record.terminalEvidenceDigest",
      { nullable: true },
    );
    if (
      snapshot.terminalEvidenceDigest !== null &&
      snapshot.observationReason !== "authenticated_persisted_receipt"
    ) {
      throw new BrowserJournalSemanticError(
        "terminal evidence digest requires authenticated_persisted_receipt",
      );
    }
    if (
      snapshot.observationReason === "authenticated_persisted_receipt" &&
      snapshot.terminalEvidenceDigest === null
    ) {
      throw new BrowserJournalSemanticError(
        "authenticated persisted terminal receipt requires evidence digest",
      );
    }
  } else {
    if (
      snapshot.status !== "indeterminate" ||
      snapshot.outcomeDigest !== null ||
      snapshot.terminalEvidenceDigest !== null
    ) {
      throw new BrowserJournalSemanticError(
        `${recordType} nonterminal record must remain indeterminate`,
      );
    }
  }
  return freezeRecord(snapshot);
}

function validateGenerationMarker(value) {
  const marker = requireRecord(value, "generation retirement record");
  exactKeys(marker, GENERATION_KEYS, "generation retirement record");
  return Object.freeze({
    profileId: stableId(marker.profileId, "retirement.profileId"),
    generation: positiveInteger(
      marker.generation,
      "retirement.generation",
    ),
  });
}

function immutableRecordEqual(left, right) {
  return IMMUTABLE_RECORD_KEYS.every((key) => left[key] === right[key]);
}

function recordEqual(left, right) {
  return RECORD_KEYS.every((key) => left[key] === right[key]);
}

function requireImmutableMatch(prior, next) {
  if (!immutableRecordEqual(prior, next)) {
    throw new BrowserJournalSemanticError(
      "journal operation identity was reused with changed immutable semantics",
    );
  }
}

function applyDispatch(records, generations, record) {
  const retired = generations.get(record.profileId) ?? 0;
  if (record.generation <= retired) {
    throw new BrowserJournalSemanticError(
      "journal dispatch attempts to resurrect a retired profile generation",
    );
  }
  const key = keyOf(record);
  const prior = records.get(key);
  if (!prior) {
    if (records.size >= MAX_RECORDS) {
      throw new BrowserJournalCapacityError(
        "browser journal record capacity exhausted",
      );
    }
    records.set(key, record);
    return true;
  }
  requireImmutableMatch(prior, record);
  // A retry of the original dispatch identity never rolls a later observation
  // backward and never appends another durable byte.
  return false;
}

function applyObservation(records, generations, record) {
  const retired = generations.get(record.profileId) ?? 0;
  if (record.generation <= retired) {
    throw new BrowserJournalSemanticError(
      "journal observation targets a retired profile generation",
    );
  }
  const key = keyOf(record);
  const prior = records.get(key);
  if (!prior) {
    throw new BrowserJournalSemanticError(
      "journal observation has no dispatch intent",
    );
  }
  requireImmutableMatch(prior, record);
  if (recordEqual(prior, record)) return false;
  if (prior.terminalObserved) {
    throw new BrowserJournalSemanticError(
      "terminal browser outcome is immutable and cannot be replaced or rolled back",
    );
  }
  records.set(key, record);
  return true;
}

function applySnapshot(records, generations, record) {
  const retired = generations.get(record.profileId) ?? 0;
  if (record.generation <= retired) {
    throw new BrowserJournalSemanticError(
      "journal snapshot attempts to resurrect a retired profile generation",
    );
  }
  const key = keyOf(record);
  const prior = records.get(key);
  if (!prior) {
    if (records.size >= MAX_RECORDS) {
      throw new BrowserJournalCapacityError(
        "browser journal record capacity exhausted",
      );
    }
    records.set(key, record);
    return true;
  }
  requireImmutableMatch(prior, record);
  if (recordEqual(prior, record)) return false;
  if (prior.terminalObserved) {
    throw new BrowserJournalSemanticError(
      "terminal browser snapshot is immutable",
    );
  }
  records.set(key, record);
  return true;
}

function applyGenerationMarker(records, generations, marker) {
  const current = generations.get(marker.profileId) ?? 0;
  if (marker.generation <= current) return false;
  const matching = [...records.entries()].filter(
    ([, record]) =>
      record.profileId === marker.profileId &&
      record.generation <= marker.generation,
  );
  if (matching.some(([, record]) => record.terminalObserved !== true)) {
    throw new BrowserJournalSemanticError(
      "generation retirement record precedes terminal operation state",
    );
  }
  for (const [key] of matching) records.delete(key);
  generations.set(marker.profileId, marker.generation);
  return true;
}

function generationKey(marker) {
  return `${marker.profileId}\u0000${marker.generation}`;
}

function makeEnvelope(type, record, schema = SCHEMA, version = RECORD_VERSION) {
  const unsigned = { schema, version, type, record };
  return Object.freeze({ ...unsigned, checksum: checksum(unsigned) });
}

function validateEnvelope(value) {
  const envelope = requireRecord(value, "journal envelope");
  exactKeys(envelope, ENVELOPE_KEYS, "journal envelope");
  if (typeof envelope.checksum !== "string") {
    throw new BrowserJournalSemanticError(
      "browser journal envelope checksum is invalid",
    );
  }
  const unsigned = {
    schema: envelope.schema,
    version: envelope.version,
    type: envelope.type,
    record: envelope.record,
  };
  if (checksum(unsigned) !== envelope.checksum) {
    throw new BrowserJournalSemanticError("browser journal checksum mismatch");
  }
  if (envelope.type === "generation_retired") {
    if (
      envelope.schema !== GENERATION_SCHEMA ||
      envelope.version !== GENERATION_VERSION
    ) {
      throw new BrowserJournalSemanticError(
        "browser journal generation schema is unsupported",
      );
    }
  } else if (
    envelope.schema !== SCHEMA ||
    envelope.version !== RECORD_VERSION
  ) {
    throw new BrowserJournalSemanticError(
      "browser journal schema/version is unsupported",
    );
  }
  if (
    envelope.type !== "dispatch" &&
    envelope.type !== "observation" &&
    envelope.type !== "snapshot" &&
    envelope.type !== "generation_retired"
  ) {
    throw new BrowserJournalSemanticError(
      "browser journal record type is unsupported",
    );
  }
  return envelope;
}

function parseLine(line) {
  if (line.length === 0 || UTF8.encode(line).byteLength > MAX_LINE_BYTES) {
    throw new BrowserJournalSemanticError(
      "browser journal line is empty or exceeds limit",
    );
  }
  let parsed;
  try {
    parsed = JSON.parse(line);
  } catch {
    throw new BrowserJournalSemanticError(
      "browser journal contains malformed JSON",
    );
  }
  return validateEnvelope(parsed);
}

function hydrateEnvelopes(envelopes) {
  const records = new Map();
  const generations = new Map();
  for (const envelope of envelopes) {
    if (envelope.type === "generation_retired") {
      applyGenerationMarker(
        records,
        generations,
        validateGenerationMarker(envelope.record),
      );
      continue;
    }
    const record = validateDurableRecord(envelope.record, envelope.type);
    if (envelope.type === "dispatch") {
      applyDispatch(records, generations, record);
    } else if (envelope.type === "observation") {
      applyObservation(records, generations, record);
    } else {
      applySnapshot(records, generations, record);
    }
  }
  return { records, generations };
}

function parseJournalBuffer(bytes, { allowRepairableTail = false } = {}) {
  if (bytes.length === 0) {
    return { envelopes: [], validPrefixLength: 0, tornTail: null };
  }
  const lastNewline = bytes.lastIndexOf(0x0a);
  const completeLength = lastNewline === -1 ? 0 : lastNewline + 1;
  const tornTail = completeLength === bytes.length
    ? null
    : bytes.subarray(completeLength);
  if (tornTail && !allowRepairableTail) {
    throw new BrowserJournalSemanticError(
      "browser journal has an incomplete/torn final fragment",
    );
  }
  const complete = bytes.subarray(0, completeLength).toString("utf8");
  const lines = complete.length === 0
    ? []
    : complete.split("\n").filter((line) => line.length > 0);
  const envelopes = lines.map(parseLine);
  return { envelopes, validPrefixLength: completeLength, tornTail };
}

function renderSnapshot(records, generations) {
  const lines = [];
  for (const record of [...records.values()].sort((left, right) =>
    keyOf(left).localeCompare(keyOf(right)))) {
    lines.push(canonical(makeEnvelope("snapshot", record)));
  }
  const markers = [...generations.entries()]
    .map(([profileId, generation]) => ({ profileId, generation }))
    .sort((left, right) => generationKey(left).localeCompare(generationKey(right)));
  for (const marker of markers) {
    lines.push(
      canonical(
        makeEnvelope(
          "generation_retired",
          marker,
          GENERATION_SCHEMA,
          GENERATION_VERSION,
        ),
      ),
    );
  }
  return lines.length === 0 ? "" : `${lines.join("\n")}\n`;
}

async function syncDirectory(path) {
  if (process.platform === "win32") return;
  const directoryFlag = constants.O_DIRECTORY ?? 0;
  const handle = await open(path, constants.O_RDONLY | directoryFlag);
  try {
    await handle.sync();
  } finally {
    await handle.close();
  }
}

async function ensurePrivateDirectory(path) {
  try {
    const info = await stat(path);
    if (!info.isDirectory()) {
      throw new TypeError("browser journal parent component is not a directory");
    }
    return false;
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  const parent = dirname(path);
  if (parent === path) {
    throw new TypeError("browser journal parent directory cannot be created");
  }
  await ensurePrivateDirectory(parent);
  try {
    await mkdir(path, { mode: 0o700 });
  } catch (error) {
    if (error?.code !== "EEXIST") throw error;
  }
  const info = await stat(path);
  if (!info.isDirectory()) {
    throw new TypeError("browser journal parent component is not a directory");
  }
  await syncDirectory(path);
  await syncDirectory(parent);
  return true;
}

async function ensureCanonicalPrivateParent(path) {
  const parent = dirname(path);
  await ensurePrivateDirectory(parent);
  const actual = await realpath(parent);
  if (actual !== resolve(parent)) {
    throw new TypeError("browser journal parent path contains a symlink");
  }
  const info = await stat(parent);
  if (!info.isDirectory()) {
    throw new TypeError("browser journal parent is not a directory");
  }
  if (process.platform !== "win32" && (info.mode & 0o077) !== 0) {
    throw new TypeError("browser journal parent permissions are too broad");
  }
  if (
    process.platform !== "win32" &&
    typeof process.geteuid === "function" &&
    info.uid !== process.geteuid()
  ) {
    throw new TypeError("browser journal parent has the wrong owner");
  }
  return parent;
}

function validatePrivateRegularFile(info, name) {
  if (!info.isFile()) {
    throw new TypeError(`${name} is not a regular file`);
  }
  if (process.platform !== "win32") {
    if ((info.mode & 0o077) !== 0) {
      throw new TypeError(`${name} permissions are too broad`);
    }
    if (info.nlink !== 1) {
      throw new TypeError(`${name} must have exactly one hard link`);
    }
    if (
      typeof process.geteuid === "function" &&
      info.uid !== process.geteuid()
    ) {
      throw new TypeError(`${name} has the wrong owner`);
    }
  }
}

function sameFileIdentity(left, right) {
  if (process.platform === "win32") return true;
  return left.dev === right.dev && left.ino === right.ino;
}

function crashAt(phase) {
  if (process.env.HEPTA_BROWSER_JOURNAL_CRASH_PHASE === phase) {
    process.exit(86);
  }
}

function sleep(milliseconds) {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, milliseconds));
}

async function linuxProcessStartTicks(pid) {
  if (process.platform !== "linux") return null;
  try {
    const text = await readFile(`/proc/${pid}/stat`, "utf8");
    const close = text.lastIndexOf(") ");
    if (close < 0) return null;
    const fields = text.slice(close + 2).trim().split(/\s+/);
    return fields[19] ?? null;
  } catch {
    return null;
  }
}

async function processIdentity(pid) {
  try {
    process.kill(pid, 0);
  } catch (error) {
    if (error?.code === "ESRCH") return null;
    if (error?.code !== "EPERM") return null;
  }
  return { pid, startTicks: await linuxProcessStartTicks(pid) };
}

async function lockIsStale(lockPath) {
  const ownerPath = join(lockPath, "owner.json");
  try {
    const bytes = await readFile(ownerPath);
    if (bytes.length === 0 || bytes.length > 4096) return false;
    const owner = JSON.parse(bytes.toString("utf8"));
    if (
      owner === null ||
      typeof owner !== "object" ||
      !Number.isSafeInteger(owner.pid) ||
      owner.pid < 1 ||
      typeof owner.token !== "string"
    ) {
      return false;
    }
    const live = await processIdentity(owner.pid);
    if (!live) return true;
    if (
      typeof owner.startTicks === "string" &&
      live.startTicks !== null &&
      owner.startTicks !== live.startTicks
    ) {
      return true;
    }
    return false;
  } catch (error) {
    if (error?.code !== "ENOENT") return false;
    try {
      const info = await stat(lockPath);
      return Date.now() - info.mtimeMs > OWNERLESS_LOCK_STALE_MS;
    } catch {
      return false;
    }
  }
}

async function acquireInterprocessLock(journalPath) {
  const lockPath = `${journalPath}.owner-lock`;
  const deadline = Date.now() + LOCK_TIMEOUT_MS;
  while (true) {
    const token = randomUUID();
    try {
      await mkdir(lockPath, { mode: 0o700 });
      const identity = await processIdentity(process.pid);
      const owner = {
        pid: process.pid,
        token,
        startTicks: identity?.startTicks ?? null,
      };
      try {
        await writeFile(
          join(lockPath, "owner.json"),
          `${JSON.stringify(owner)}\n`,
          { mode: 0o600, flag: "wx" },
        );
      } catch (error) {
        await rm(lockPath, { recursive: true, force: true });
        throw error;
      }
      return async () => {
        let current;
        try {
          current = JSON.parse(
            await readFile(join(lockPath, "owner.json"), "utf8"),
          );
        } catch (error) {
          throw new Error("browser journal owner lock cannot be verified", {
            cause: error,
          });
        }
        if (current?.token !== token || current?.pid !== process.pid) {
          throw new Error("browser journal owner lock identity changed");
        }
        await rm(lockPath, { recursive: true, force: false });
      };
    } catch (error) {
      if (error?.code !== "EEXIST") throw error;
      if (await lockIsStale(lockPath)) {
        const stale = `${lockPath}.stale.${randomUUID()}`;
        try {
          await rename(lockPath, stale);
          await rm(stale, { recursive: true, force: true });
          continue;
        } catch (reclaimError) {
          if (
            reclaimError?.code !== "ENOENT" &&
            reclaimError?.code !== "EEXIST"
          ) {
            throw reclaimError;
          }
        }
      }
      if (Date.now() >= deadline) {
        const locked = new Error(
          "browser journal interprocess owner lock deadline exceeded",
        );
        locked.name = "BrowserJournalLockedError";
        throw locked;
      }
      await sleep(LOCK_RETRY_MS);
    }
  }
}

export class MemoryBrowserOperationJournal {
  durable = false;
  #records = new Map();
  #retiredGenerations = new Map();

  async assertProfileGenerationAvailable(profileId, generation) {
    const checkedProfileId = stableId(profileId, "profileId");
    const checkedGeneration = positiveInteger(generation, "generation");
    const retired = this.#retiredGenerations.get(checkedProfileId) ?? 0;
    if (checkedGeneration <= retired) {
      throw new BrowserJournalSemanticError(
        "profile generation is retired and cannot be reopened",
      );
    }
    const active = [...this.#records.values()].filter(
      (record) => record.profileId === checkedProfileId,
    );
    if (active.some((record) => record.generation === checkedGeneration)) {
      throw new BrowserJournalSemanticError(
        "profile generation already has durable operation history",
      );
    }
    if (active.some((record) => record.terminalObserved !== true)) {
      throw new BrowserJournalSemanticError(
        "another profile generation still has unresolved operations",
      );
    }
    if (active.length > 0) {
      throw new BrowserJournalSemanticError(
        "prior terminal profile generation requires explicit retirement",
      );
    }
  }

  async recordDispatch(record) {
    const snapshot = validateDurableRecord({ ...record }, "dispatch");
    applyDispatch(this.#records, this.#retiredGenerations, snapshot);
  }

  async recordObservation(record) {
    const snapshot = validateDurableRecord({ ...record }, "observation");
    applyObservation(this.#records, this.#retiredGenerations, snapshot);
  }

  async getOperation(profileId, generation, operationId) {
    return (
      this.#records.get(
        `${stableId(profileId, "profileId")}\u0000${positiveInteger(
          generation,
          "generation",
        )}\u0000${stableId(operationId, "operationId")}`,
      ) ?? null
    );
  }

  async listOperations(profileId, generation) {
    const prefix = `${stableId(profileId, "profileId")}\u0000${positiveInteger(
      generation,
      "generation",
    )}\u0000`;
    return [...this.#records.entries()]
      .filter(([key]) => key.startsWith(prefix))
      .map(([, value]) => value);
  }

  async retireProfile(profileId, generation) {
    const marker = validateGenerationMarker({ profileId, generation });
    const retired = this.#retiredGenerations.get(marker.profileId) ?? 0;
    if (marker.generation <= retired) return;
    const matching = [...this.#records.entries()].filter(
      ([, record]) =>
        record.profileId === marker.profileId &&
        record.generation === marker.generation,
    );
    if (matching.length === 0) {
      throw new BrowserJournalSemanticError(
        "profile generation has no durable operations to retire",
      );
    }
    if (matching.some(([, record]) => record.terminalObserved !== true)) {
      throw new BrowserJournalSemanticError(
        "profile generation has unresolved operations and cannot retire",
      );
    }
    const other = [...this.#records.values()].filter(
      (record) =>
        record.profileId === marker.profileId &&
        record.generation !== marker.generation,
    );
    if (other.length > 0) {
      throw new BrowserJournalSemanticError(
        "profile generation retirement is not the sole active generation",
      );
    }
    for (const [key] of matching) this.#records.delete(key);
    this.#retiredGenerations.set(marker.profileId, marker.generation);
  }
}

export class FileBrowserOperationJournal {
  durable = true;
  #path;
  #tail = Promise.resolve();
  #fencedError = null;
  #maximumFileBytes;
  #compactAtBytes;

  constructor(
    path,
    {
      maximumFileBytes = DEFAULT_MAX_FILE_BYTES,
      compactAtBytes = DEFAULT_COMPACT_AT_BYTES,
    } = {},
  ) {
    if (typeof path !== "string" || !isAbsolute(path)) {
      throw new TypeError("browser journal path must be absolute");
    }
    positiveInteger(maximumFileBytes, "maximumFileBytes");
    positiveInteger(compactAtBytes, "compactAtBytes");
    if (compactAtBytes > maximumFileBytes) {
      throw new TypeError("compactAtBytes cannot exceed maximumFileBytes");
    }
    this.#path = path;
    this.#maximumFileBytes = maximumFileBytes;
    this.#compactAtBytes = compactAtBytes;
  }

  async assertProfileGenerationAvailable(profileId, generation) {
    const checkedProfileId = stableId(profileId, "profileId");
    const checkedGeneration = positiveInteger(generation, "generation");
    return this.#serialize(async () => {
      const { records, generations } = await this.#loadForOwner();
      const retired = generations.get(checkedProfileId) ?? 0;
      if (checkedGeneration <= retired) {
        throw new BrowserJournalSemanticError(
          "profile generation is retired and cannot be reopened",
        );
      }
      const active = [...records.values()].filter(
        (record) => record.profileId === checkedProfileId,
      );
      if (active.some((record) => record.generation === checkedGeneration)) {
        throw new BrowserJournalSemanticError(
          "profile generation already has durable operation history",
        );
      }
      if (active.some((record) => record.terminalObserved !== true)) {
        throw new BrowserJournalSemanticError(
          "another profile generation still has unresolved operations",
        );
      }
      if (active.length > 0) {
        throw new BrowserJournalSemanticError(
          "prior terminal profile generation requires explicit retirement",
        );
      }
    });
  }

  async recordDispatch(record) {
    const snapshot = validateDurableRecord({ ...record }, "dispatch");
    return this.#serialize(async () => {
      const loaded = await this.#loadForOwner();
      const changed = applyDispatch(
        loaded.records,
        loaded.generations,
        snapshot,
      );
      if (!changed) return;
      await this.#appendForOwner(makeEnvelope("dispatch", snapshot));
      await this.#compactIfNeededForOwner();
    });
  }

  async recordObservation(record) {
    const snapshot = validateDurableRecord({ ...record }, "observation");
    return this.#serialize(async () => {
      const loaded = await this.#loadForOwner();
      const changed = applyObservation(
        loaded.records,
        loaded.generations,
        snapshot,
      );
      if (!changed) return;
      await this.#appendForOwner(makeEnvelope("observation", snapshot));
      await this.#compactIfNeededForOwner();
    });
  }

  async getOperation(profileId, generation, operationId) {
    const checkedProfileId = stableId(profileId, "profileId");
    const checkedGeneration = positiveInteger(generation, "generation");
    const checkedOperationId = stableId(operationId, "operationId");
    return this.#serialize(async () => {
      const { records } = await this.#loadForOwner();
      return (
        records.get(
          `${checkedProfileId}\u0000${checkedGeneration}\u0000${checkedOperationId}`,
        ) ?? null
      );
    });
  }

  async listOperations(profileId, generation) {
    const checkedProfileId = stableId(profileId, "profileId");
    const checkedGeneration = positiveInteger(generation, "generation");
    return this.#serialize(async () => {
      const { records } = await this.#loadForOwner();
      const prefix = `${checkedProfileId}\u0000${checkedGeneration}\u0000`;
      return [...records.entries()]
        .filter(([key]) => key.startsWith(prefix))
        .map(([, value]) => value);
    });
  }

  async retireProfile(profileId, generation) {
    const marker = validateGenerationMarker({ profileId, generation });
    return this.#serialize(async () => {
      const loaded = await this.#loadForOwner();
      const retired = loaded.generations.get(marker.profileId) ?? 0;
      if (marker.generation <= retired) return;
      const matching = [...loaded.records.values()].filter(
        (record) =>
          record.profileId === marker.profileId &&
          record.generation === marker.generation,
      );
      if (matching.length === 0) {
        throw new BrowserJournalSemanticError(
          "profile generation has no durable operations to retire",
        );
      }
      if (matching.some((record) => record.terminalObserved !== true)) {
        throw new BrowserJournalSemanticError(
          "profile generation has unresolved operations and cannot retire",
        );
      }
      const other = [...loaded.records.values()].filter(
        (record) =>
          record.profileId === marker.profileId &&
          record.generation !== marker.generation,
      );
      if (other.length > 0) {
        throw new BrowserJournalSemanticError(
          "profile generation retirement is not the sole active generation",
        );
      }
      await this.#appendForOwner(
        makeEnvelope(
          "generation_retired",
          marker,
          GENERATION_SCHEMA,
          GENERATION_VERSION,
        ),
      );
      applyGenerationMarker(loaded.records, loaded.generations, marker);
      await this.#rewriteSnapshotForOwner(
        loaded.records,
        loaded.generations,
        "retire",
      );
    });
  }

  async compact() {
    return this.#serialize(async () => {
      const { records, generations } = await this.#loadForOwner();
      await this.#rewriteSnapshotForOwner(records, generations, "compact");
    });
  }

  async recoverFencedPrefix() {
    return this.#serialize(
      async () => {
        const inspection = await this.#inspectRepairableFinalTailForOwner();
        if (inspection.tornTail === null) {
          throw new BrowserJournalSemanticError(
            "browser journal has no repairable torn final fragment",
          );
        }
        try {
          const parsed = JSON.parse(inspection.tornTail.toString("utf8"));
          validateEnvelope(parsed);
          throw new BrowserJournalSemanticError(
            "browser journal final bytes contain a valid final record; refusing repair",
          );
        } catch (error) {
          if (
            error instanceof BrowserJournalSemanticError &&
            error.message.includes("valid final record")
          ) {
            throw error;
          }
        }
        try {
          await truncate(this.#path, inspection.validPrefixLength);
          const noFollow = constants.O_NOFOLLOW ?? 0;
          const handle = await open(
            this.#path,
            constants.O_WRONLY | noFollow,
          );
          try {
            await handle.sync();
          } finally {
            await handle.close();
          }
          await syncDirectory(dirname(this.#path));
          this.#fencedError = null;
        } catch (error) {
          this.#fence(error);
          throw error;
        }
      },
      { recovery: true },
    );
  }

  async #loadForOwner() {
    try {
      return await this.#load();
    } catch (error) {
      this.#fence(error);
      throw error;
    }
  }

  async #appendForOwner(envelope) {
    try {
      await this.#append(envelope);
    } catch (error) {
      if (!(error instanceof BrowserJournalSemanticError)) this.#fence(error);
      throw error;
    }
  }

  async #compactIfNeededForOwner() {
    try {
      const info = await stat(this.#path);
      if (info.size >= this.#compactAtBytes) {
        const { records, generations } = await this.#load();
        await this.#rewriteSnapshot(records, generations, "compact");
      }
    } catch (error) {
      if (!(error instanceof BrowserJournalSemanticError)) this.#fence(error);
      throw error;
    }
  }

  async #rewriteSnapshotForOwner(records, generations, reason) {
    try {
      await this.#rewriteSnapshot(records, generations, reason);
    } catch (error) {
      if (!(error instanceof BrowserJournalSemanticError)) this.#fence(error);
      throw error;
    }
  }

  async #load() {
    await ensureCanonicalPrivateParent(this.#path);
    const noFollow = constants.O_NOFOLLOW ?? 0;
    let handle;
    try {
      handle = await open(this.#path, constants.O_RDONLY | noFollow);
    } catch (error) {
      if (error?.code === "ENOENT") {
        return { records: new Map(), generations: new Map(), bytesLength: 0 };
      }
      throw error;
    }
    let bytes;
    try {
      const info = await handle.stat();
      validatePrivateRegularFile(info, "browser journal");
      if (info.size > this.#maximumFileBytes) {
        throw new BrowserJournalCapacityError(
          "browser journal exceeds configured capacity",
        );
      }
      const pathInfo = await stat(this.#path);
      if (!sameFileIdentity(info, pathInfo)) {
        throw new TypeError("browser journal changed during secure open");
      }
      bytes = await handle.readFile();
    } finally {
      await handle.close();
    }
    const parsed = parseJournalBuffer(bytes);
    const hydrated = hydrateEnvelopes(parsed.envelopes);
    return { ...hydrated, bytesLength: bytes.length };
  }

  async #append(envelope) {
    const line = `${canonical(envelope)}\n`;
    const lineBytes = UTF8.encode(line).byteLength;
    if (lineBytes > MAX_LINE_BYTES) {
      throw new BrowserJournalCapacityError(
        "browser journal record exceeds line limit",
      );
    }
    const parent = await ensureCanonicalPrivateParent(this.#path);
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const flags =
      constants.O_WRONLY | constants.O_APPEND | constants.O_CREAT | noFollow;
    const handle = await open(this.#path, flags, 0o600);
    try {
      const info = await handle.stat();
      validatePrivateRegularFile(info, "browser journal");
      if (info.size + lineBytes > this.#maximumFileBytes) {
        throw new BrowserJournalCapacityError(
          "browser journal capacity exhausted",
        );
      }
      const pathInfo = await stat(this.#path);
      if (!sameFileIdentity(info, pathInfo)) {
        throw new TypeError("browser journal changed during append open");
      }
      await handle.writeFile(line, "utf8");
      await handle.sync();
    } finally {
      await handle.close();
    }
    await syncDirectory(parent);
  }

  async #rewriteSnapshot(records, generations, reason) {
    const contents = renderSnapshot(records, generations);
    const size = UTF8.encode(contents).byteLength;
    if (size > this.#maximumFileBytes) {
      throw new BrowserJournalCapacityError(
        "compacted browser journal exceeds configured capacity",
      );
    }
    const parent = await ensureCanonicalPrivateParent(this.#path);
    const temporary = `${this.#path}.${reason}.${randomUUID()}.tmp`;
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const flags =
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | noFollow;
    let renamed = false;
    try {
      const handle = await open(temporary, flags, 0o600);
      try {
        if (contents.length > 0) await handle.writeFile(contents, "utf8");
        await handle.sync();
      } finally {
        await handle.close();
      }
      crashAt("after-temp-fsync");
      await rename(temporary, this.#path);
      renamed = true;
      crashAt("after-rename");
      await syncDirectory(parent);
      crashAt("after-directory-fsync");
    } finally {
      if (!renamed) await rm(temporary, { force: true });
    }
  }

  async #inspectRepairableFinalTailForOwner() {
    try {
      return await this.#inspectRepairableFinalTail();
    } catch (error) {
      if (!(error instanceof BrowserJournalSemanticError)) this.#fence(error);
      throw error;
    }
  }

  async #inspectRepairableFinalTail() {
    await ensureCanonicalPrivateParent(this.#path);
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const handle = await open(this.#path, constants.O_RDONLY | noFollow);
    let bytes;
    try {
      const info = await handle.stat();
      validatePrivateRegularFile(info, "browser journal");
      if (info.size > this.#maximumFileBytes) {
        throw new BrowserJournalCapacityError(
          "browser journal exceeds configured capacity",
        );
      }
      bytes = await handle.readFile();
    } finally {
      await handle.close();
    }
    const parsed = parseJournalBuffer(bytes, { allowRepairableTail: true });
    hydrateEnvelopes(parsed.envelopes);
    if (parsed.tornTail && parsed.tornTail.length > MAX_LINE_BYTES) {
      throw new BrowserJournalCapacityError(
        "browser journal torn final fragment exceeds line limit",
      );
    }
    return parsed;
  }

  #fence(error) {
    if (this.#fencedError !== null) return;
    const fenced = new Error(
      `browser journal owner is fenced pending explicit recovery: ${String(
        error?.message ?? error,
      )}`,
      { cause: error },
    );
    fenced.name = "BrowserJournalRecoveryRequiredError";
    this.#fencedError = fenced;
  }

  #serialize(operation, { recovery = false } = {}) {
    const run = this.#tail.catch(() => {}).then(async () => {
      if (!recovery && this.#fencedError !== null) throw this.#fencedError;
      await ensureCanonicalPrivateParent(this.#path);
      const release = await acquireInterprocessLock(this.#path);
      let result;
      let operationError;
      try {
        result = await operation();
      } catch (error) {
        operationError = error;
      }
      try {
        await release();
      } catch (error) {
        this.#fence(error);
        throw error;
      }
      if (operationError !== undefined) throw operationError;
      return result;
    });
    this.#tail = run.catch(() => {});
    return run;
  }
}

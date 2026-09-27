import { createHash, randomUUID } from "node:crypto";
import { acquireBrowserJournalLock, BrowserJournalLockedError } from "./journal-owner-lock.js";
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
const GENERATION_SCHEMA = "hepta.browser.profile-generation-retirement.v1";
const MAX_LINE_BYTES = 262_144;
const MAX_RETIRED_BYTES = 8 * 1024 * 1024;
const MAX_RETIRED_PROFILES = 65_536;
const MAX_LIVE_RECORDS = 65_536;
const MAX_FILE_BYTES = 64 * 1024 * 1024;
const COMPACT_AT_BYTES = 48 * 1024 * 1024;
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
    UTF8.encode(value).byteLength > 512
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
  if (terminalEvidenceDigest !== null && record.observationReason !== "authenticated_persisted_receipt") {
    throw new TypeError("terminal evidence requires authenticated_persisted_receipt");
  }
  if (type === "dispatch" && (record.status !== "indeterminate" || record.observationReason !== "dispatching")) {
    throw new TypeError("dispatch journal record must begin indeterminate dispatching");
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
    throw new JournalSemanticError("profile has unresolved durable effects from another generation");
  }
  if ([...records.values()].some(record => record.profileId === profileId)) {
    throw new JournalSemanticError("prior terminal profile generation requires explicit retirement");
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
    if (record.profileId === profileId && record.generation !== generation) {
      throw new JournalSemanticError("retirement must target the sole active profile generation");
    }
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

const ADMISSION_SCHEMA = "hepta.browser.worker-admission.v1";
function validateAdmission(record, records, retired) {
  const value = requireRecord(record, "worker admission record");
  exactKeys(value, ["admission", "generation", "operationId", "profileId", "requestDigest", "semanticDigest"], "worker admission record");
  stableId(value.profileId, "profileId"); positiveInteger(value.generation, "generation"); stableId(value.operationId, "operationId");
  digest(value.requestDigest, "requestDigest"); digest(value.semanticDigest, "semanticDigest");
  assertGenerationAvailable(retired, value.profileId, value.generation);
  const prior = records.get(keyOf(value));
  if (!prior || prior.requestDigest !== value.requestDigest || prior.semanticDigest !== value.semanticDigest) {
    throw new JournalSemanticError("worker admission does not bind a durable dispatch identity");
  }
  const admission = requireRecord(value.admission, "worker admission");
  exactKeys(admission, ["admittedAt", "durableOrRecoverable", "kind", "operationId", "pageRevision", "semanticDigest", "workerGeneration"], "worker admission");
  if (admission.kind !== "BrowserEffectAdmissionV1" || admission.operationId !== value.operationId ||
      admission.semanticDigest !== value.semanticDigest || admission.workerGeneration !== value.generation ||
      admission.pageRevision !== prior.pageGeneration || admission.durableOrRecoverable !== true ||
      positiveInteger(admission.admittedAt, "admittedAt") >= prior.deadlineMs) {
    throw new JournalSemanticError("worker admission receipt drifted from durable semantics");
  }
  return Object.freeze({
    admission: Object.freeze({
      admittedAt: admission.admittedAt, durableOrRecoverable: true,
      kind: admission.kind, operationId: admission.operationId,
      pageRevision: admission.pageRevision, semanticDigest: admission.semanticDigest,
      workerGeneration: admission.workerGeneration,
    }),
    generation: value.generation, operationId: value.operationId,
    profileId: value.profileId, requestDigest: value.requestDigest,
    semanticDigest: value.semanticDigest,
  });
}
function storeAdmission(state, record) {
  const value = validateAdmission(record, state.records, state.retired);
  const key = keyOf(value);
  const prior = state.admissions.get(key);
  if (prior) {
    if (JSON.stringify(prior) !== JSON.stringify(value)) throw new JournalSemanticError("worker admission is immutable");
    return null;
  }
  state.admissions.set(key, value);
  return value;
}
function admissionLine(record) {
  const unsigned = { schema: ADMISSION_SCHEMA, version: 1, type: "admission", record };
  return `${canonical({ ...unsigned, checksum: checksum(unsigned) })}\n`;
}

const EGRESS_SCHEMA = "hepta.browser.egress-operation-receipt.v1";
const EGRESS_KEYS = ["schema", "operationId", "profileGrantDigest", "effectGrantDigest", "destinationOrigin", "status", "admittedAtMs", "completedAtMs", "requestBytes", "responseBytes", "connectionCount", "boundedAbort", "maxRequestBytes", "maxResponseBytes"];

function storeEgress(state, record) {
  const value = requireRecord(record, "egress journal record");
  exactKeys(value, ["generation", "operationId", "profileId", "receipt", "requestDigest", "semanticDigest"], "egress journal record");
  stableId(value.profileId, "profileId"); positiveInteger(value.generation, "generation"); stableId(value.operationId, "operationId");
  assertGenerationAvailable(state.retired, value.profileId, value.generation);
  const operation = state.records.get(keyOf(value));
  if (!operation || value.requestDigest !== operation.requestDigest || value.semanticDigest !== operation.semanticDigest) {
    throw new JournalSemanticError("egress receipt does not bind a durable dispatch identity");
  }
  const receipt = requireRecord(value.receipt, "egress receipt");
  exactKeys(receipt, [...EGRESS_KEYS, "receiptDigest"].sort(), "egress receipt");
  const unsigned = Object.fromEntries(EGRESS_KEYS.map(key => [key, receipt[key]]));
  if (unsigned.schema !== EGRESS_SCHEMA || unsigned.operationId !== operation.operationId ||
      unsigned.profileGrantDigest !== operation.profileGrantDigest || unsigned.effectGrantDigest !== operation.effectGrantDigest ||
      unsigned.destinationOrigin !== operation.destinationOrigin || checksum(unsigned) !== receipt.receiptDigest) {
    throw new JournalSemanticError("egress receipt identity or checksum drifted");
  }
  boundedReason(unsigned.status);
  if (unsigned.status.length > 64 || typeof unsigned.boundedAbort !== "boolean") throw new JournalSemanticError("egress receipt status/abort is invalid");
  const admitted = positiveInteger(unsigned.admittedAtMs, "egress admittedAtMs");
  const completed = positiveInteger(unsigned.completedAtMs, "egress completedAtMs");
  if (admitted >= operation.deadlineMs || completed < admitted) throw new JournalSemanticError("egress receipt time does not bind the original operation");
  for (const key of ["requestBytes", "responseBytes", "connectionCount"]) nonNegativeInteger(unsigned[key], key);
  positiveInteger(unsigned.maxRequestBytes, "maxRequestBytes"); positiveInteger(unsigned.maxResponseBytes, "maxResponseBytes");
  if (unsigned.connectionCount > 64 || unsigned.maxRequestBytes > 16 * 1024 * 1024 || unsigned.maxResponseBytes > 256 * 1024 * 1024 ||
      (!unsigned.boundedAbort && (unsigned.requestBytes > unsigned.maxRequestBytes || unsigned.responseBytes > unsigned.maxResponseBytes))) {
    throw new JournalSemanticError("egress receipt exceeds its non-aborted resource budget");
  }
  const snapshot = Object.freeze({ generation: value.generation, operationId: value.operationId, profileId: value.profileId,
    receipt: Object.freeze({ ...unsigned, receiptDigest: receipt.receiptDigest }), requestDigest: value.requestDigest, semanticDigest: value.semanticDigest });
  const prior = state.egress.get(keyOf(value));
  if (prior) {
    if (canonical(prior) !== canonical(snapshot)) throw new JournalSemanticError("durable egress receipt is immutable");
    return null;
  }
  state.egress.set(keyOf(value), snapshot);
  return snapshot;
}
function egressLine(record) {
  const unsigned = { schema: EGRESS_SCHEMA, version: 1, type: "egress", record };
  return `${canonical({ ...unsigned, checksum: checksum(unsigned) })}\n`;
}

export class MemoryBrowserOperationJournal {
  durable = false;
  #records = new Map();
  #retired = new Map();
  #admissions = new Map();
  #egress = new Map();

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
    assertGenerationAvailable(this.#retired, snapshot.profileId, snapshot.generation);
    applyTransition(this.#records, "observation", snapshot);
  }

  async recordAdmission(record) {
    storeAdmission({ records: this.#records, retired: this.#retired, admissions: this.#admissions }, record);
  }
  async getAdmission(profileId, generation, operationId) {
    return this.#admissions.get(`${profileId}\0${generation}\0${operationId}`) ?? null;
  }

  async recordEgress(record) {
    storeEgress({ records: this.#records, retired: this.#retired, egress: this.#egress }, record);
  }
  async getEgress(profileId, generation, operationId) {
    return this.#egress.get(`${profileId}\0${generation}\0${operationId}`) ?? null;
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
    if (generation > prior) {
      if (!this.#retired.has(profileId) && this.#retired.size >= MAX_RETIRED_PROFILES) {
        throw new JournalSemanticError("retired profile capacity exhausted");
      }
      this.#retired.set(profileId, generation);
    }
    const prefix = profilePrefix(profileId, generation);
    for (const key of [...this.#records.keys()]) {
      if (key.startsWith(prefix)) { this.#records.delete(key); this.#admissions.delete(key); this.#egress.delete(key); }
    }
  }
}

function validatePrivateFile(info, maximum, label) {
  if (!info.isFile() || info.size > BigInt(maximum) || info.nlink !== 1n ||
      (info.mode & 0o077n) !== 0n || info.uid !== BigInt(process.geteuid())) {
    throw new TypeError(`${label} must be a bounded private singly-linked owner file`);
  }
}
function stamp(info) {
  return info ? [info.dev, info.ino, info.size, info.mtimeNs, info.ctimeNs].join(":") : "absent";
}
async function fileInfo(path) {
  try { return await lstat(path, { bigint: true }); }
  catch (error) { if (error?.code === "ENOENT") return null; throw error; }
}
function markerLine(profileId, generation) {
  const record = { profileId: stableId(profileId, "profileId"), generation: positiveInteger(generation, "generation") };
  const unsigned = { schema: GENERATION_SCHEMA, version: 1, type: "generation_retired", record };
  return `${canonical({ ...unsigned, checksum: checksum(unsigned) })}\n`;
}
function applyRetirement(records, retired, profileId, generation) {
  stableId(profileId, "profileId"); positiveInteger(generation, "generation");
  if (generation <= (retired.get(profileId) ?? 0)) return;
  if (!retired.has(profileId) && retired.size >= MAX_RETIRED_PROFILES) {
    throw new JournalSemanticError("retired profile generation capacity exhausted");
  }
  for (const [key, record] of records) {
    if (record.profileId === profileId && record.generation <= generation) {
      if (!record.terminalObserved) throw new TypeError("retirement precedes terminal operation state");
      records.delete(key);
    }
  }
  retired.set(profileId, generation);
}

export class FileBrowserOperationJournal {
  durable = true;
  #path;
  #tail = Promise.resolve();
  #faultInjector;
  #fencedCause = null;
  #cache = null;
  #maximumFileBytes;
  #compactAtBytes;
  #stats = { diskReadBytes: 0, fullLoads: 0, cacheHits: 0, appends: 0, compactions: 0 };

  constructor(path, { faultInjector = null, maximumFileBytes = MAX_FILE_BYTES, compactAtBytes = COMPACT_AT_BYTES } = {}) {
    if (typeof path !== "string" || !isAbsolute(path)) throw new TypeError("browser journal path must be absolute");
    if (faultInjector !== null && typeof faultInjector !== "function") throw new TypeError("faultInjector must be a function or null");
    positiveInteger(maximumFileBytes, "maximumFileBytes");
    positiveInteger(compactAtBytes, "compactAtBytes");
    if (maximumFileBytes > MAX_FILE_BYTES || compactAtBytes > maximumFileBytes) throw new TypeError("journal capacity exceeds hard bounds");
    this.#path = path;
    this.#faultInjector = faultInjector;
    this.#maximumFileBytes = maximumFileBytes;
    this.#compactAtBytes = compactAtBytes;
  }

  get statistics() { return Object.freeze({ ...this.#stats }); }

  async assertProfileGenerationAvailable(profileId, generation) {
    stableId(profileId, "profileId"); positiveInteger(generation, "generation");
    return this.#serialize(async () => {
      const { records, retired } = await this.#load();
      assertGenerationAvailable(retired, profileId, generation);
      assertGenerationHistoryClear(records, profileId, generation);
    });
  }
  async recordDispatch(record) { return this.#record(record, "dispatch"); }
  async recordObservation(record) { return this.#record(record, "observation"); }
  async #record(record, type) {
    const snapshot = validateDurableRecord(record, type);
    return this.#serialize(async () => {
      const state = await this.#load();
      assertGenerationAvailable(state.retired, snapshot.profileId, snapshot.generation);
      if (!applyTransition(state.records, type, snapshot)) return;
      await this.#append(envelopeLine(type, snapshot), state);
      this.#indexRecord(state, snapshot);
      if (state.size >= this.#compactAtBytes) await this.#rewrite(state);
    });
  }
  async recordAdmission(record) {
    // Freeze the entry-time identity before waiting for another owner.
    const snapshot = structuredClone(record);
    return this.#serialize(async () => {
      const state = await this.#load();
      const value = storeAdmission(state, snapshot);
      if (value) await this.#append(admissionLine(value), state);
    });
  }
  async getAdmission(profileId, generation, operationId) {
    stableId(profileId, "profileId"); positiveInteger(generation, "generation"); stableId(operationId, "operationId");
    return this.#serialize(async () => (await this.#load()).admissions.get(`${profileId}\0${generation}\0${operationId}`) ?? null);
  }

  async recordEgress(record) {
    const snapshot = structuredClone(record);
    return this.#serialize(async () => {
      const state = await this.#load();
      const value = storeEgress(state, snapshot);
      if (value) await this.#append(egressLine(value), state);
    });
  }
  async getEgress(profileId, generation, operationId) {
    stableId(profileId, "profileId"); positiveInteger(generation, "generation"); stableId(operationId, "operationId");
    return this.#serialize(async () => (await this.#load()).egress.get(`${profileId}\0${generation}\0${operationId}`) ?? null);
  }

  async getOperation(profileId, generation, operationId) {
    stableId(profileId, "profileId"); positiveInteger(generation, "generation"); stableId(operationId, "operationId");
    return this.#serialize(async () => (await this.#load()).records.get(`${profileId}\0${generation}\0${operationId}`) ?? null);
  }
  async listOperations(profileId, generation) {
    stableId(profileId, "profileId"); positiveInteger(generation, "generation");
    return this.#serialize(async () => [...((await this.#load()).byProfile.get(`${profileId}\0${generation}`)?.values() ?? [])]);
  }
  async compact() { return this.#serialize(async () => this.#rewrite(await this.#load())); }
  async retireProfile(profileId, generation) {
    stableId(profileId, "profileId"); positiveInteger(generation, "generation");
    return this.#serialize(async () => {
      const state = await this.#load();
      if (generation <= (state.retired.get(profileId) ?? 0)) return;
      assertRetirable(state.records, profileId, generation);
      if (!state.retired.has(profileId) && state.retired.size >= MAX_RETIRED_PROFILES) throw new JournalSemanticError("retired profile capacity exhausted");
      // The exact #1064 inline marker is the durable non-resurrection point.
      // Empty profiles retire too; starting a worker need not have sent effects.
      await this.#append(markerLine(profileId, generation), state);
      applyRetirement(state.records, state.retired, profileId, generation);
      this.#reindex(state);
      this.#fault("retired_high_water_committed_before_journal_rewrite");
      await this.#rewrite(state);
    });
  }

  async recoverFencedPrefix() {
    return this.#serialize(async () => {
      this.#cache = null;
      const info = await fileInfo(this.#path);
      if (!info) throw new JournalSemanticError("no journal prefix to recover");
      const bytes = await this.#readPrivate(this.#path, this.#maximumFileBytes);
      if (!bytes.length || bytes.at(-1) === 10) throw new JournalSemanticError("no repairable torn final fragment");
      await this.#load();
      this.#fencedCause = null;
    }, true);
  }

  async #serialize(operation, recovery = false) {
    const run = this.#tail.catch(() => {}).then(async () => {
      if (this.#fencedCause && !recovery) {
        const error = new Error(`browser journal owner requires recovery (fenced): ${this.#fencedCause.message}`);
        error.name = "BrowserJournalOwnerFencedError"; error.code = "BROWSER_JOURNAL_OWNER_FENCED";
        throw error;
      }
      let release;
      try {
        await ensureCanonicalPrivateParent(this.#path);
        const parent = await lstat(dirname(this.#path));
        if (parent.uid !== process.geteuid()) throw new TypeError("browser journal parent has the wrong owner");
        release = await acquireBrowserJournalLock(this.#path);
        const result = await operation();
        const unlock = release; release = null;
        await unlock();
        return result;
      } catch (error) {
        this.#cache = null;
        if (!(error instanceof JournalSemanticError) && !(error instanceof BrowserJournalLockedError)) this.#fencedCause ??= error;
        throw error;
      } finally {
        if (release) {
          try { await release(); }
          catch (error) { this.#cache = null; this.#fencedCause ??= error; throw error; }
        }
      }
    });
    this.#tail = run.catch(() => {});
    return run;
  }

  async #readPrivate(path, maximum) {
    const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
    try {
      const info = await handle.stat({ bigint: true });
      validatePrivateFile(info, maximum, "browser journal");
      const pathInfo = await fileInfo(path);
      if (!pathInfo || stamp(pathInfo) !== stamp(info)) throw new Error("journal changed during secure open");
      const bytes = await handle.readFile();
      if (bytes.length > maximum) throw new TypeError("browser journal grew beyond capacity");
      this.#stats.diskReadBytes += bytes.length;
      return bytes;
    } finally { await handle.close(); }
  }

  async #load() {
    try { return await this.#loadValidated(); }
    catch (error) { this.#cache = null; this.#fencedCause ??= error; throw error; }
  }
  async #loadValidated() {
    const info = await fileInfo(this.#path);
    const retiredInfo = await fileInfo(`${this.#path}.retired`);
    if (info) validatePrivateFile(info, this.#maximumFileBytes, "browser journal");
    if (retiredInfo) validatePrivateFile(retiredInfo, MAX_RETIRED_BYTES, "legacy retired journal");
    const identity = stamp(info), legacyIdentity = stamp(retiredInfo);
    if (this.#cache?.identity === identity && this.#cache.legacyIdentity === legacyIdentity) {
      this.#stats.cacheHits++;
      return this.#cache;
    }
    this.#stats.fullLoads++;
    const state = { records: new Map(), retired: new Map(), admissions: new Map(), egress: new Map(), byProfile: new Map(), identity, legacyIdentity, size: 0 };
    const bytes = info ? await this.#readPrivate(this.#path, this.#maximumFileBytes) : Buffer.alloc(0);
    state.size = bytes.length;
    const completeLength = bytes.length === 0 ? 0 : bytes.lastIndexOf(10) + 1;
    const tail = bytes.subarray(completeLength);
    if (tail.length > MAX_LINE_BYTES) throw new TypeError("journal torn final fragment exceeds line bound");
    let rewrite = tail.length !== 0;
    const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes.subarray(0, completeLength));
    const lines = text.length ? text.slice(0, -1).split("\n") : [];
    for (const line of lines) {
      if (!line.length || Buffer.byteLength(line) > MAX_LINE_BYTES) throw new TypeError("browser journal line is empty or exceeds limit");
      let envelope;
      try { envelope = requireRecord(JSON.parse(line), "browser journal envelope"); }
      catch { throw new TypeError("browser journal contains malformed JSON"); }
      exactKeys(envelope, ["checksum", "record", "schema", "type", "version"], "browser journal envelope");
      const { schema, version, type, record } = envelope;
      if (checksum({ schema, version, type, record }) !== envelope.checksum) throw new TypeError("browser journal checksum mismatch");
      if (type === "egress" && schema === EGRESS_SCHEMA && version === 1) {
        storeEgress(state, record);
        continue;
      }
      if (type === "admission" && schema === ADMISSION_SCHEMA && version === 1) {
        storeAdmission(state, record);
        continue;
      }
      if (type === "generation_retired" && schema === GENERATION_SCHEMA && version === 1) {
        requireRecord(record, "retirement marker"); exactKeys(record, ["generation", "profileId"], "retirement marker");
        applyRetirement(state.records, state.retired, record.profileId, record.generation);
        continue;
      }
      if (!["dispatch", "observation", "snapshot"].includes(type)) throw new TypeError("journal record type is unsupported");
      let normalized;
      if (schema === SCHEMA && version === 2) normalized = validateDurableRecord(record, type);
      else if (schema === LEGACY_SCHEMA && version === 1) { normalized = migrateLegacyRecord(record, type); rewrite = true; }
      else throw new TypeError("browser journal schema/version is unsupported");
      assertGenerationAvailable(state.retired, normalized.profileId, normalized.generation);
      applyTransition(state.records, type, normalized);
    }
    // Explicit compatibility with the reviewed predecessor's sidecar. It is
    // never written again; absorb its monotonic facts into the inline journal.
    // All legacy processes MUST be stopped before the owner-lock upgrade.
    if (retiredInfo) {
      const legacy = JSON.parse((await this.#readPrivate(`${this.#path}.retired`, MAX_RETIRED_BYTES)).toString("utf8"));
      exactKeys(requireRecord(legacy, "legacy retirement"), ["checksum", "profiles", "schema", "version"], "legacy retirement");
      const { schema, version, profiles } = legacy;
      if (schema !== RETIRED_SCHEMA || version !== 1 || checksum({ schema, version, profiles }) !== legacy.checksum) throw new TypeError("legacy retirement schema/checksum mismatch");
      requireRecord(profiles, "legacy retired profiles");
      if (Object.keys(profiles).length > MAX_RETIRED_PROFILES) throw new TypeError("legacy retired profile capacity exceeded");
      for (const [id, gen] of Object.entries(profiles)) {
        if (gen > (state.retired.get(id) ?? 0)) { applyRetirement(state.records, state.retired, id, gen); rewrite = true; }
      }
    }
    this.#reindex(state);
    if (rewrite) { await this.#rewrite(state); this.#fault("torn_prefix_repaired"); }
    else this.#cache = state;
    return state;
  }

  #indexRecord(state, record) {
    const id = `${record.profileId}\0${record.generation}`;
    let group = state.byProfile.get(id);
    if (!group) { group = new Map(); state.byProfile.set(id, group); }
    group.set(record.operationId, record);
  }
  #reindex(state) {
    state.byProfile = new Map();
    for (const record of state.records.values()) this.#indexRecord(state, record);
    for (const key of state.admissions.keys()) if (!state.records.has(key)) state.admissions.delete(key);
    for (const key of state.egress.keys()) if (!state.records.has(key)) state.egress.delete(key);
  }
  async #publishCache(state) {
    const info = await fileInfo(this.#path);
    if (!info) throw new Error("journal disappeared before cache publication");
    validatePrivateFile(info, this.#maximumFileBytes, "browser journal");
    state.identity = stamp(info); state.size = Number(info.size); this.#cache = state;
  }
  async #append(line, state) {
    const bytes = Buffer.byteLength(line);
    if (bytes > MAX_LINE_BYTES) throw new JournalSemanticError("browser journal record exceeds line bound");
    // The staged transition already exists in the private map. Publishing a
    // snapshot at capacity includes that transition atomically, not twice.
    if (state.size + bytes > this.#maximumFileBytes) {
      if (JSON.parse(line).type === "generation_retired") {
        const { profileId, generation } = JSON.parse(line).record;
        applyRetirement(state.records, state.retired, profileId, generation);
        this.#reindex(state);
      }
      await this.#rewrite(state);
      return;
    }
    let created = false, handle;
    try {
      try {
        handle = await open(this.#path, constants.O_WRONLY | constants.O_APPEND | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
        created = true;
      } catch (error) {
        if (error?.code !== "EEXIST") throw error;
        handle = await open(this.#path, constants.O_WRONLY | constants.O_APPEND | constants.O_NOFOLLOW);
      }
      const info = await handle.stat({ bigint: true });
      validatePrivateFile(info, this.#maximumFileBytes, "browser journal");
      if ((!created && stamp(info) !== state.identity) || (created && state.identity !== "absent")) throw new Error("journal identity changed under owner lock");
      await handle.writeFile(line, "utf8");
      await handle.sync();
      if (created) this.#fault("append_created_fsynced_before_parent_fsync");
      if (JSON.parse(line).type === "generation_retired") this.#fault("retire_marker_fsynced_before_parent_fsync");
    } finally { await handle?.close(); }
    await syncDirectory(dirname(this.#path));
    this.#stats.appends++;
    await this.#publishCache(state);
  }
  async #rewrite(state) {
    const body = [...state.records.entries()].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)
      .map(([, record]) => envelopeLine("snapshot", record)).join("") +
      [...state.admissions.entries()].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)
        .map(([, record]) => admissionLine(record)).join("") +
      [...state.egress.entries()].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)
        .map(([, record]) => egressLine(record)).join("") +
      [...state.retired.entries()].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)
        .map(([id, generation]) => markerLine(id, generation)).join("");
    if (Buffer.byteLength(body) > this.#maximumFileBytes) throw new JournalSemanticError("browser journal live snapshot capacity exhausted");
    const temporary = `${this.#path}.compact-${process.pid}-${randomUUID()}`;
    let renamed = false;
    try {
      const handle = await open(temporary, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
      try {
        await handle.writeFile(body, "utf8"); await handle.sync();
        this.#fault("compact_temp_fsynced_before_rename");
        this.#crash("after-temp-fsync");
      } finally { await handle.close(); }
      await rename(temporary, this.#path); renamed = true;
      this.#fault("compact_renamed_before_parent_fsync");
      this.#crash("after-rename");
      await syncDirectory(dirname(this.#path));
      this.#crash("after-directory-fsync");
      this.#stats.compactions++;
      await this.#publishCache(state);
    } finally { if (!renamed) await rm(temporary, { force: true }); }
  }
  #fault(name) { this.#faultInjector?.(name); }
  #crash(phase) { if (process.env.HEPTA_BROWSER_JOURNAL_CRASH_PHASE === phase) process.exit(86); }
}

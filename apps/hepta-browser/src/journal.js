import { createHash } from "node:crypto";
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

const SCHEMA = "hepta.browser.operation-journal.v1";
const RETIRED_SCHEMA = "hepta.browser.retired-profile-generations.v1";
const MAX_LINE_BYTES = 262_144;
const MAX_RETIRED_BYTES = 8 * 1024 * 1024;
const MAX_RETIRED_PROFILES = 65_536;
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
  "terminalObserved",
  "verifiedUseTokenWitnessDigest",
].sort();

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

function matchesWeb(url) {
  return url.protocol === "http:" || url.protocol === "https:";
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
  if (record.status === "indeterminate") {
    if (record.terminalObserved !== false || record.outcomeDigest !== null) {
      throw new TypeError(
        "indeterminate journal record cannot claim a terminal outcome",
      );
    }
  } else {
    if (record.terminalObserved !== true) {
      throw new TypeError("terminal journal status requires terminalObserved=true");
    }
    digest(record.outcomeDigest, "outcomeDigest");
  }
  if (type === "dispatch" && record.status !== "indeterminate") {
    throw new TypeError("dispatch journal record must begin indeterminate");
  }
  return Object.freeze({ ...record });
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
    if (record.terminalObserved !== true) {
      unresolvedOtherGeneration = true;
    }
  }
  if (sameGenerationHistory) {
    throw new TypeError(
      "profile generation has durable operation history and cannot be reopened",
    );
  }
  if (unresolvedOtherGeneration) {
    throw new TypeError(
      "profile has unresolved durable effects from another generation",
    );
  }
}

function assertGenerationAvailable(retired, profileId, generation) {
  stableId(profileId, "profileId");
  positiveInteger(generation, "generation");
  const highWater = retired.get(profileId);
  if (highWater !== undefined && generation <= highWater) {
    throw new TypeError("profile generation has already been retired");
  }
}

async function ensureCanonicalPrivateParent(path) {
  const parent = dirname(path);
  await mkdir(parent, { recursive: true, mode: 0o700 });
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
  if (actual !== resolve(parent)) {
    throw new TypeError("browser journal parent path contains a symlink");
  }
}

function envelopeLine(type, record) {
  const validated = validateDurableRecord(
    record,
    type === "snapshot" ? "snapshot" : type,
  );
  const unsigned = { schema: SCHEMA, version: 1, type, record: validated };
  const line = `${canonical({ ...unsigned, checksum: checksum(unsigned) })}\n`;
  if (UTF8.encode(line).byteLength > MAX_LINE_BYTES) {
    throw new TypeError("browser journal record exceeds line limit");
  }
  return line;
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
    const key = keyOf(snapshot);
    const prior = this.#records.get(key);
    if (prior && prior.requestDigest !== snapshot.requestDigest) {
      throw new TypeError(
        "journal operation identity was reused with changed semantics",
      );
    }
    this.#records.set(key, snapshot);
  }

  async recordObservation(record) {
    const snapshot = validateDurableRecord(record, "observation");
    const key = keyOf(snapshot);
    const prior = this.#records.get(key);
    if (!prior) throw new TypeError("journal observation has no dispatch intent");
    if (
      prior.requestDigest !== snapshot.requestDigest ||
      prior.semanticDigest !== snapshot.semanticDigest
    ) {
      throw new TypeError("journal observation changed immutable semantics");
    }
    this.#records.set(key, snapshot);
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
  #tail = Promise.resolve();
  #rewriteCounter = 0;

  constructor(path) {
    if (typeof path !== "string" || !isAbsolute(path)) {
      throw new TypeError("browser journal path must be absolute");
    }
    this.#path = path;
    this.#retiredPath = `${path}.retired`;
  }

  async assertProfileGenerationAvailable(profileId, generation) {
    return this.#serialize(async () => {
      const retired = await this.#loadRetired();
      assertGenerationAvailable(retired, profileId, generation);
      const records = await this.#load();
      assertGenerationHistoryClear(records, profileId, generation);
    });
  }

  async recordDispatch(record) {
    return this.#serialize(async () => {
      const snapshot = validateDurableRecord(record, "dispatch");
      const prior = await this.#getOperationUnlocked(
        snapshot.profileId,
        snapshot.generation,
        snapshot.operationId,
      );
      if (prior && prior.requestDigest !== snapshot.requestDigest) {
        throw new TypeError(
          "journal operation identity was reused with changed semantics",
        );
      }
      const size = await this.#append({ type: "dispatch", record: snapshot });
      if (size >= COMPACT_AT_BYTES) await this.#compactUnlocked();
    });
  }

  async recordObservation(record) {
    return this.#serialize(async () => {
      const snapshot = validateDurableRecord(record, "observation");
      const prior = await this.#getOperationUnlocked(
        snapshot.profileId,
        snapshot.generation,
        snapshot.operationId,
      );
      if (!prior) throw new TypeError("journal observation has no dispatch intent");
      if (
        prior.requestDigest !== snapshot.requestDigest ||
        prior.semanticDigest !== snapshot.semanticDigest
      ) {
        throw new TypeError("journal observation changed immutable semantics");
      }
      const size = await this.#append({ type: "observation", record: snapshot });
      if (size >= COMPACT_AT_BYTES) await this.#compactUnlocked();
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
      const prefix = profilePrefix(profileId, generation);
      return [...records.entries()]
        .filter(([key]) => key.startsWith(prefix))
        .map(([, value]) => value);
    });
  }

  async compact() {
    return this.#serialize(() => this.#compactUnlocked());
  }

  async retireProfile(profileId, generation) {
    stableId(profileId, "profileId");
    positiveInteger(generation, "generation");
    return this.#serialize(async () => {
      // Persist the non-resurrection fence first. A crash can therefore leave
      // redundant terminal operation records, but can never erase operation
      // identity and then make the same retired generation admissible again.
      const retired = await this.#loadRetired();
      const prior = retired.get(profileId) ?? 0;
      if (generation > prior) {
        if (!retired.has(profileId) && retired.size >= MAX_RETIRED_PROFILES) {
          throw new TypeError("retired profile generation capacity is exhausted");
        }
        retired.set(profileId, generation);
        await this.#rewriteRetired(retired);
      }

      const records = await this.#load();
      const prefix = profilePrefix(profileId, generation);
      for (const key of [...records.keys()]) {
        if (key.startsWith(prefix)) records.delete(key);
      }
      await this.#rewrite(records);
    });
  }

  async #getOperationUnlocked(profileId, generation, operationId) {
    const records = await this.#load();
    return (
      records.get(`${profileId}\u0000${generation}\u0000${operationId}`) ?? null
    );
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
    const object = requireRecord(
      envelope,
      "retired profile generation ledger",
    );
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
    const sorted = [...profileIds].sort();
    if (profileIds.some((profileId, index) => profileId !== sorted[index])) {
      throw new TypeError(
        "retired profile generation ledger is not canonical",
      );
    }
    const retired = new Map();
    for (const profileId of profileIds) {
      stableId(profileId, "retired profileId");
      const generation = positiveInteger(
        profiles[profileId],
        "retired generation",
      );
      retired.set(profileId, generation);
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
      throw new TypeError(
        "retired profile generation ledger is not canonical",
      );
    }
    return retired;
  }

  async #rewriteRetired(retired) {
    if (!(retired instanceof Map)) {
      throw new TypeError("retired profile generation state must be a Map");
    }
    if (retired.size > MAX_RETIRED_PROFILES) {
      throw new TypeError("retired profile generation ledger exceeds capacity");
    }
    const profiles = Object.fromEntries(
      [...retired.entries()]
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([profileId, generation]) => {
          stableId(profileId, "retired profileId");
          return [
            profileId,
            positiveInteger(generation, "retired generation"),
          ];
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
      throw new TypeError("retired profile generation ledger exceeds byte limit");
    }

    await ensureCanonicalPrivateParent(this.#retiredPath);
    const temporary =
      `${this.#retiredPath}.tmp-${process.pid}-${this.#rewriteCounter++}`;
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
      await rename(temporary, this.#retiredPath);
      const parent = await open(
        dirname(this.#retiredPath),
        constants.O_RDONLY | noFollow,
      );
      try {
        await parent.sync();
      } finally {
        await parent.close();
      }
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
      const object = requireRecord(envelope, "browser journal envelope");
      exactKeys(
        object,
        ["checksum", "record", "schema", "type", "version"].sort(),
        "browser journal envelope",
      );
      if (
        object.schema !== SCHEMA ||
        object.version !== 1 ||
        typeof object.checksum !== "string"
      ) {
        throw new TypeError("browser journal envelope is unsupported");
      }
      if (!matchesRecordType(object.type)) {
        throw new TypeError("browser journal record type is unsupported");
      }
      const unsigned = {
        schema: object.schema,
        version: object.version,
        type: object.type,
        record: object.record,
      };
      if (checksum(unsigned) !== object.checksum) {
        throw new TypeError("browser journal checksum mismatch");
      }
      const record = validateDurableRecord(
        object.record,
        object.type === "snapshot" ? "snapshot" : object.type,
      );
      const key = keyOf(record);
      const prior = records.get(key);
      if (object.type === "dispatch") {
        if (prior && prior.requestDigest !== record.requestDigest) {
          throw new TypeError(
            "browser journal contains conflicting dispatch identity",
          );
        }
        records.set(key, record);
      } else if (object.type === "observation") {
        if (!prior) {
          throw new TypeError("browser journal observation precedes dispatch");
        }
        if (
          prior.requestDigest !== record.requestDigest ||
          prior.semanticDigest !== record.semanticDigest
        ) {
          throw new TypeError("browser journal observation changed semantics");
        }
        records.set(key, record);
      } else {
        if (
          prior &&
          (prior.requestDigest !== record.requestDigest ||
            prior.semanticDigest !== record.semanticDigest)
        ) {
          throw new TypeError(
            "browser journal snapshot conflicts with prior semantics",
          );
        }
        records.set(key, record);
      }
    }
    return records;
  }

  async #append({ type, record }, allowCompact = true) {
    const line = envelopeLine(type, record);
    const lineBytes = UTF8.encode(line).byteLength;
    await ensureCanonicalPrivateParent(this.#path);
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const flags =
      constants.O_WRONLY | constants.O_APPEND | constants.O_CREAT | noFollow;
    let handle = await open(this.#path, flags, 0o600);
    try {
      const info = await handle.stat();
      if (!info.isFile()) {
        throw new TypeError("browser journal is not a regular file");
      }
      if (process.platform !== "win32" && (info.mode & 0o077) !== 0) {
        throw new TypeError("browser journal permissions are too broad");
      }
      if (info.size + lineBytes > MAX_FILE_BYTES) {
        if (!allowCompact) {
          throw new TypeError("browser journal capacity exhausted after compaction");
        }
        await handle.close();
        handle = null;
        await this.#compactUnlocked();
        return this.#append({ type, record }, false);
      }
      await handle.writeFile(line, "utf8");
      await handle.sync();
      return info.size + lineBytes;
    } finally {
      await handle?.close();
    }
  }

  async #compactUnlocked() {
    const records = await this.#load();
    await this.#rewrite(records);
  }

  async #rewrite(records) {
    await ensureCanonicalPrivateParent(this.#path);
    const body = [...records.values()]
      .map((record) => envelopeLine("snapshot", record))
      .join("");
    const bytes = UTF8.encode(body);
    if (bytes.byteLength > MAX_FILE_BYTES) {
      throw new TypeError(
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
    } finally {
      await handle.close();
    }
    try {
      await rename(temporary, this.#path);
      const parent = await open(dirname(this.#path), constants.O_RDONLY | noFollow);
      try {
        await parent.sync();
      } finally {
        await parent.close();
      }
    } catch (error) {
      await rm(temporary, { force: true }).catch(() => {});
      throw error;
    }
  }

  #serialize(operation) {
    const run = this.#tail.catch(() => {}).then(operation);
    this.#tail = run.catch(() => {});
    return run;
  }
}

function matchesRecordType(value) {
  return value === "dispatch" || value === "observation" || value === "snapshot";
}

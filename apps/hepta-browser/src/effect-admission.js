import {
  canonicalDigest,
  digest,
  nonNegativeInteger,
  positiveInteger,
  requireRecord,
  stableId,
} from "./runtime-contract.js";

const ADMISSION_KEYS = [
  "admittedAt",
  "durableOrRecoverable",
  "kind",
  "operationId",
  "pageRevision",
  "semanticDigest",
  "workerGeneration",
].sort();

function exactKeys(value, expected, name) {
  const keys = Object.keys(value).sort();
  if (
    keys.length !== expected.length ||
    keys.some((key, index) => key !== expected[index])
  ) {
    throw new TypeError(`${name} contains missing or unknown fields`);
  }
}

export function browserEffectPageRevision(effect) {
  const input = requireRecord(effect, "browser effect semantics");
  const profileId = stableId(input.profileId, "effect.profileId");
  const workerGeneration = positiveInteger(
    input.profileGeneration ?? input.generation,
    "effect.profileGeneration",
  );
  const pageGeneration = nonNegativeInteger(
    input.pageGeneration,
    "effect.pageGeneration",
  );
  const documentDigest =
    input.documentDigest === null
      ? null
      : digest(input.documentDigest, "effect.documentDigest");
  return canonicalDigest({
    schema: "hepta.browser.page-revision.v1",
    profileId,
    workerGeneration,
    pageGeneration,
    documentDigest,
  });
}

export function createBrowserEffectAdmission(
  effect,
  { clock = () => Date.now() } = {},
) {
  if (typeof clock !== "function") {
    throw new TypeError("admission clock must be a function");
  }
  const semantics = requireRecord(effect, "browser effect semantics");
  const admittedAt = Math.max(1, Math.trunc(clock()));
  positiveInteger(admittedAt, "admittedAt");
  return Object.freeze({
    kind: "BrowserEffectAdmissionV1",
    operationId: stableId(semantics.operationId, "effect.operationId"),
    semanticDigest: canonicalDigest(semantics),
    workerGeneration: positiveInteger(
      semantics.profileGeneration ?? semantics.generation,
      "effect.profileGeneration",
    ),
    pageRevision: browserEffectPageRevision(semantics),
    admittedAt,
    durableOrRecoverable: true,
  });
}

export function normalizeBrowserEffectAdmission(value, expected = {}) {
  const admission = requireRecord(value, "BrowserEffectAdmissionV1");
  exactKeys(admission, ADMISSION_KEYS, "BrowserEffectAdmissionV1");
  if (admission.kind !== "BrowserEffectAdmissionV1") {
    throw new TypeError("browser effect admission kind is unsupported");
  }
  const normalized = Object.freeze({
    kind: admission.kind,
    operationId: stableId(admission.operationId, "admission.operationId"),
    semanticDigest: digest(
      admission.semanticDigest,
      "admission.semanticDigest",
    ),
    workerGeneration: positiveInteger(
      admission.workerGeneration,
      "admission.workerGeneration",
    ),
    pageRevision: digest(admission.pageRevision, "admission.pageRevision"),
    admittedAt: positiveInteger(admission.admittedAt, "admission.admittedAt"),
    durableOrRecoverable: admission.durableOrRecoverable,
  });
  if (normalized.durableOrRecoverable !== true) {
    throw new TypeError(
      "browser effect admission must be durable or independently recoverable",
    );
  }
  for (const [field, expectedValue] of Object.entries(expected)) {
    if (expectedValue !== undefined && normalized[field] !== expectedValue) {
      throw new TypeError(
        `browser effect admission ${field} does not bind the admitted effect`,
      );
    }
  }
  return normalized;
}

export class AdmissionBoundBrowserDriver {
  supportsAbort;
  maxActiveProfiles;
  maxOutstandingOperations;

  #driver;
  #clock;

  constructor({ driver, clock = () => Date.now() }) {
    requireRecord(driver, "browser driver");
    for (const method of [
      "start",
      "observe",
      "dispatch",
      "reconcile",
      "reconcilePersisted",
      "contain",
      "stop",
    ]) {
      if (typeof driver[method] !== "function") {
        throw new TypeError(`browser driver.${method} must be a function`);
      }
    }
    if (driver.supportsAbort !== true) {
      throw new TypeError("admission-bound browser driver requires abort support");
    }
    if (typeof clock !== "function") {
      throw new TypeError("admission clock must be a function");
    }
    this.#driver = driver;
    this.#clock = clock;
    this.supportsAbort = true;
    this.maxActiveProfiles = positiveInteger(
      driver.maxActiveProfiles,
      "driver.maxActiveProfiles",
    );
    this.maxOutstandingOperations = positiveInteger(
      driver.maxOutstandingOperations,
      "driver.maxOutstandingOperations",
    );
  }

  start(input, context) {
    return this.#driver.start(input, context);
  }

  observe(input, context) {
    return this.#driver.observe(input, context);
  }

  async dispatch(input, context) {
    const observed = requireRecord(
      await this.#driver.dispatch(input, context),
      "browser driver dispatch observation",
    );
    if (observed.terminalObserved !== false) {
      throw new TypeError(
        "driver dispatch must return at the worker admission boundary",
      );
    }
    const admission = createBrowserEffectAdmission(input, {
      clock: this.#clock,
    });
    return Object.freeze({ ...observed, admission });
  }

  reconcile(input, context) {
    return this.#driver.reconcile(input, context);
  }

  reconcilePersisted(input, context) {
    return this.#driver.reconcilePersisted(input, context);
  }

  contain(input, context) {
    return this.#driver.contain(input, context);
  }

  stop(input, context) {
    return this.#driver.stop(input, context);
  }
}

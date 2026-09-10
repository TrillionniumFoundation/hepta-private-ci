import { createHash } from "node:crypto";

const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);
const MAX_ORIGINS = 128;
const MAX_EFFECT_GRANTS = 1024;
const MAX_OUTSTANDING_OPERATIONS = 1024;

function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

function stableId(value, name) {
  if (typeof value !== "string" || !STABLE_ID.test(value)) {
    throw new TypeError(`${name} must be a bounded stable identifier`);
  }
  return value;
}

function digest(value, name) {
  if (typeof value !== "string" || !DIGEST.test(value) || value === ZERO_DIGEST) {
    throw new TypeError(`${name} must be a non-zero lowercase SHA-256 digest`);
  }
  return value;
}

function positiveInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

function deadline(value, now, name = "deadlineMs") {
  const deadlineMs = positiveInteger(value, name);
  if (deadlineMs <= now) {
    throw new TypeError(`${name} has expired`);
  }
  return deadlineMs;
}

function canonicalOrigin(value) {
  const url = new URL(value);
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new TypeError("origin must use HTTP or HTTPS");
  }
  if (url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new TypeError("origin must not contain credentials, path, query, or fragment");
  }
  return url.origin;
}

function canonicalDigest(value) {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function freezeResult(value) {
  return Object.freeze({
    ...value,
    networkAuthority: false,
    filesystemAuthority: false,
    credentialExportAuthority: false,
  });
}

function parseEffectGrant(value, now, allowedOrigins) {
  const grant = requireRecord(value, "effectGrant");
  const grantDigest = digest(grant.grantDigest, "effectGrant.grantDigest");
  const action = stableId(grant.action, "effectGrant.action");
  const destinationOrigin = canonicalOrigin(grant.destinationOrigin);
  if (!allowedOrigins.has(destinationOrigin)) {
    throw new TypeError("effect grant destination is outside the profile grant");
  }
  const finalPayloadDigest = digest(
    grant.finalPayloadDigest,
    "effectGrant.finalPayloadDigest",
  );
  const authorityEpoch = positiveInteger(grant.authorityEpoch, "effectGrant.authorityEpoch");
  const expiresAtMs = deadline(grant.expiresAtMs, now, "effectGrant.expiresAtMs");
  return Object.freeze({
    grantDigest,
    action,
    destinationOrigin,
    finalPayloadDigest,
    authorityEpoch,
    expiresAtMs,
  });
}

export class BrowserProfileHost {
  #driver;
  #clock;
  #profiles = new Map();

  constructor({ driver, clock = () => Date.now() }) {
    requireRecord(driver, "driver");
    for (const method of ["start", "observe", "act", "reconcile", "stop"]) {
      if (typeof driver[method] !== "function") {
        throw new TypeError(`driver.${method} must be a function`);
      }
    }
    if (typeof clock !== "function") {
      throw new TypeError("clock must be a function");
    }
    this.#driver = driver;
    this.#clock = clock;
  }

  async openProfile(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    const principalId = stableId(input.principalId, "principalId");
    const manifestDigest = digest(input.manifestDigest, "manifestDigest");
    const grantDigest = digest(input.grantDigest, "grantDigest");
    const generation = positiveInteger(input.generation, "generation");
    const expiresAtMs = deadline(input.expiresAtMs, this.#clock(), "expiresAtMs");
    if (!Array.isArray(input.allowedOrigins) || input.allowedOrigins.length > MAX_ORIGINS) {
      throw new TypeError("allowedOrigins is not a bounded array");
    }
    const allowedOrigins = new Set(input.allowedOrigins.map(canonicalOrigin));
    if (allowedOrigins.size !== input.allowedOrigins.length) {
      throw new TypeError("allowedOrigins contains duplicates");
    }
    if (
      !Array.isArray(input.effectGrants) ||
      input.effectGrants.length === 0 ||
      input.effectGrants.length > MAX_EFFECT_GRANTS
    ) {
      throw new TypeError("effectGrants must be a non-empty bounded array");
    }
    const effectGrants = new Map();
    for (const rawGrant of input.effectGrants) {
      const grant = parseEffectGrant(rawGrant, this.#clock(), allowedOrigins);
      if (effectGrants.has(grant.grantDigest)) {
        throw new TypeError("effectGrants contains duplicate grantDigest");
      }
      effectGrants.set(grant.grantDigest, grant);
    }
    if (this.#profiles.has(profileId)) {
      throw new TypeError("profile is already open");
    }

    const observed = requireRecord(
      await this.#driver.start({
        profileId,
        principalId,
        manifestDigest,
        grantDigest,
        generation,
        allowedOrigins: [...allowedOrigins],
      }),
      "driver start observation",
    );
    if (observed.started !== true) {
      throw new TypeError("driver did not observe profile start");
    }
    const processId = stableId(observed.processId, "processId");
    const state = {
      profileId,
      principalId,
      manifestDigest,
      grantDigest,
      generation,
      expiresAtMs,
      processId,
      pageGeneration: 0,
      documentDigest: null,
      allowedOrigins,
      effectGrants,
      operations: new Map(),
    };
    this.#profiles.set(profileId, state);
    return freezeResult({
      kind: "BrowserSessionV1",
      profileId,
      principalId,
      processId,
      generation,
      manifestDigest,
      grantDigest,
      expiresAtMs,
      effectGrantCount: effectGrants.size,
    });
  }

  async observePage(input) {
    const state = this.#profile(input);
    const observationBudget = positiveInteger(input.observationBudget, "observationBudget");
    if (observationBudget > 1_000_000) {
      throw new TypeError("observationBudget exceeds profile limit");
    }
    const observed = requireRecord(
      await this.#driver.observe({
        profileId: state.profileId,
        processId: state.processId,
        generation: state.generation,
        observationBudget,
      }),
      "driver page observation",
    );
    const pageGeneration = positiveInteger(observed.pageGeneration, "pageGeneration");
    if (pageGeneration <= state.pageGeneration) {
      throw new TypeError("page generation did not advance");
    }
    const documentDigest = digest(observed.documentDigest, "documentDigest");
    const origin = canonicalOrigin(observed.origin);
    state.pageGeneration = pageGeneration;
    state.documentDigest = documentDigest;
    return freezeResult({
      kind: "PageObservationV1",
      profileId: state.profileId,
      processId: state.processId,
      profileGeneration: state.generation,
      pageGeneration,
      documentDigest,
      origin,
      originAllowed: state.allowedOrigins.has(origin),
      terminalObserved: true,
    });
  }

  async navigateOrAct(input) {
    const admitted = this.#admitOperation(input);
    const { state, operationId, semantics, semanticDigest } = admitted;
    const prior = state.operations.get(operationId);
    if (prior) {
      if (prior.semanticDigest !== semanticDigest) {
        throw new TypeError("operation identity was reused with changed semantics");
      }
      return prior.receipt;
    }
    if (state.operations.size >= MAX_OUTSTANDING_OPERATIONS) {
      throw new TypeError("profile operation capacity is exhausted");
    }

    const observed = requireRecord(
      await this.#driver.act(semantics),
      "driver effect observation",
    );
    const receipt = this.#effectReceipt(state.profileId, operationId, semanticDigest, observed);
    state.operations.set(operationId, { semanticDigest, semantics, receipt });
    return receipt;
  }

  async reconcileOperation(input) {
    const admitted = this.#admitOperation(input);
    const { state, operationId, semantics, semanticDigest } = admitted;
    const prior = state.operations.get(operationId);
    if (!prior) {
      throw new TypeError("operation has not crossed the browser effect boundary");
    }
    if (prior.semanticDigest !== semanticDigest) {
      throw new TypeError("operation reconciliation changed immutable semantics");
    }
    if (prior.receipt.terminalObserved === true) {
      return prior.receipt;
    }
    const observed = requireRecord(
      await this.#driver.reconcile(semantics),
      "driver reconciliation observation",
    );
    const receipt = this.#effectReceipt(state.profileId, operationId, semanticDigest, observed);
    if (receipt.terminalObserved === true) {
      prior.receipt = receipt;
    }
    return receipt;
  }

  async closeProfile(input) {
    const state = this.#profile(input);
    if ([...state.operations.values()].some((entry) => entry.receipt.terminalObserved !== true)) {
      throw new TypeError("profile has indeterminate browser effects requiring reconciliation");
    }
    const observed = requireRecord(
      await this.#driver.stop({
        profileId: state.profileId,
        processId: state.processId,
        generation: state.generation,
      }),
      "driver stop observation",
    );
    if (observed.stopped !== true) {
      throw new TypeError("driver did not observe profile stop");
    }
    this.#profiles.delete(state.profileId);
    return freezeResult({
      kind: "BrowserProfileClosedV1",
      profileId: state.profileId,
      processId: state.processId,
      generation: state.generation,
      terminalObserved: true,
    });
  }

  #admitOperation(input) {
    const state = this.#profile(input);
    const operationId = stableId(input.operationId, "operationId");
    const pageGeneration = positiveInteger(input.pageGeneration, "pageGeneration");
    if (pageGeneration !== state.pageGeneration || state.documentDigest === null) {
      throw new TypeError("stale page generation");
    }
    const action = stableId(input.action, "action");
    const destinationOrigin = canonicalOrigin(input.destinationOrigin);
    if (!state.allowedOrigins.has(destinationOrigin)) {
      throw new TypeError("destination origin is outside the profile grant");
    }
    const finalPayloadDigest = digest(input.finalPayloadDigest, "finalPayloadDigest");
    const effectGrantDigest = digest(input.effectGrantDigest, "effectGrantDigest");
    const authorityEpoch = positiveInteger(input.authorityEpoch, "authorityEpoch");
    const deadlineMs = deadline(input.deadlineMs, this.#clock());
    const grant = state.effectGrants.get(effectGrantDigest);
    if (!grant) {
      throw new TypeError("effect grant is not registered for this profile");
    }
    if (this.#clock() >= grant.expiresAtMs) {
      throw new TypeError("effect grant has expired");
    }
    if (
      grant.action !== action ||
      grant.destinationOrigin !== destinationOrigin ||
      grant.finalPayloadDigest !== finalPayloadDigest ||
      grant.authorityEpoch !== authorityEpoch
    ) {
      throw new TypeError("effect grant does not bind the final browser operation");
    }
    const semantics = Object.freeze({
      profileId: state.profileId,
      principalId: state.principalId,
      processId: state.processId,
      profileGeneration: state.generation,
      pageGeneration,
      documentDigest: state.documentDigest,
      operationId,
      action,
      destinationOrigin,
      finalPayloadDigest,
      profileGrantDigest: state.grantDigest,
      effectGrantDigest,
      authorityEpoch,
      deadlineMs,
    });
    return {
      state,
      operationId,
      semantics,
      semanticDigest: canonicalDigest(semantics),
    };
  }

  #effectReceipt(profileId, operationId, semanticDigest, observed) {
    if (observed.terminalObserved !== true) {
      return freezeResult({
        kind: "BrowserEffectObservationV1",
        profileId,
        operationId,
        semanticDigest,
        status: "indeterminate",
        outcomeDigest: null,
        terminalObserved: false,
      });
    }
    if (observed.status !== "succeeded" && observed.status !== "failed") {
      throw new TypeError("terminal browser status is not registered");
    }
    return freezeResult({
      kind: "BrowserEffectObservationV1",
      profileId,
      operationId,
      semanticDigest,
      status: observed.status,
      outcomeDigest: digest(observed.outcomeDigest, "outcomeDigest"),
      terminalObserved: true,
    });
  }

  #profile(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    const state = this.#profiles.get(profileId);
    if (!state) {
      throw new TypeError("profile is not open");
    }
    if (input.principalId !== state.principalId) {
      throw new TypeError("principal does not own the profile");
    }
    if (input.generation !== state.generation) {
      throw new TypeError("profile generation mismatch");
    }
    if (this.#clock() >= state.expiresAtMs) {
      throw new TypeError("profile grant has expired");
    }
    return state;
  }
}

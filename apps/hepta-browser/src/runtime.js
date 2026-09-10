const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);
const MAX_ORIGINS = 128;
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

function deadline(value, now) {
  const deadlineMs = positiveInteger(value, "deadlineMs");
  if (deadlineMs <= now) {
    throw new TypeError("deadline has expired");
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

function freezeResult(value) {
  return Object.freeze({
    ...value,
    networkAuthority: false,
    filesystemAuthority: false,
    credentialExportAuthority: false,
  });
}

export class BrowserProfileHost {
  #driver;
  #clock;
  #profiles = new Map();

  constructor({ driver, clock = () => Date.now() }) {
    requireRecord(driver, "driver");
    for (const method of ["start", "observe", "act", "stop"]) {
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
    const expiresAtMs = deadline(input.expiresAtMs, this.#clock());
    if (!Array.isArray(input.allowedOrigins) || input.allowedOrigins.length > MAX_ORIGINS) {
      throw new TypeError("allowedOrigins is not a bounded array");
    }
    const allowedOrigins = new Set(input.allowedOrigins.map(canonicalOrigin));
    if (allowedOrigins.size !== input.allowedOrigins.length) {
      throw new TypeError("allowedOrigins contains duplicates");
    }
    if (this.#profiles.has(profileId)) {
      throw new TypeError("profile is already open");
    }

    const observed = requireRecord(
      await this.#driver.start({
        profileId,
        principalId,
        manifestDigest,
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
      allowedOrigins,
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
    const state = this.#profile(input);
    const operationId = stableId(input.operationId, "operationId");
    const pageGeneration = positiveInteger(input.pageGeneration, "pageGeneration");
    const finalPayloadDigest = digest(input.finalPayloadDigest, "finalPayloadDigest");
    const grantPayloadDigest = digest(input.grantPayloadDigest, "grantPayloadDigest");
    deadline(input.deadlineMs, this.#clock());
    if (pageGeneration !== state.pageGeneration) {
      throw new TypeError("stale page generation");
    }
    if (finalPayloadDigest !== grantPayloadDigest) {
      throw new TypeError("grant does not bind the final payload");
    }
    const destinationOrigin = canonicalOrigin(input.destinationOrigin);
    if (!state.allowedOrigins.has(destinationOrigin)) {
      throw new TypeError("destination origin is outside the profile grant");
    }
    if (state.operations.size >= MAX_OUTSTANDING_OPERATIONS) {
      throw new TypeError("profile operation capacity is exhausted");
    }
    const prior = state.operations.get(operationId);
    if (prior) {
      if (prior.finalPayloadDigest !== finalPayloadDigest) {
        throw new TypeError("operation identity was reused with changed semantics");
      }
      return prior.receipt;
    }

    const observed = requireRecord(
      await this.#driver.act({
        profileId: state.profileId,
        processId: state.processId,
        profileGeneration: state.generation,
        pageGeneration,
        operationId,
        action: stableId(input.action, "action"),
        destinationOrigin,
        finalPayloadDigest,
      }),
      "driver effect observation",
    );
    let receipt;
    if (observed.terminalObserved !== true) {
      receipt = freezeResult({
        kind: "BrowserEffectObservationV1",
        profileId: state.profileId,
        operationId,
        status: "indeterminate",
        outcomeDigest: null,
        terminalObserved: false,
      });
    } else {
      if (observed.status !== "succeeded" && observed.status !== "failed") {
        throw new TypeError("terminal browser status is not registered");
      }
      receipt = freezeResult({
        kind: "BrowserEffectObservationV1",
        profileId: state.profileId,
        operationId,
        status: observed.status,
        outcomeDigest: digest(observed.outcomeDigest, "outcomeDigest"),
        terminalObserved: true,
      });
    }
    state.operations.set(operationId, { finalPayloadDigest, receipt });
    return receipt;
  }

  async closeProfile(input) {
    const state = this.#profile(input);
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

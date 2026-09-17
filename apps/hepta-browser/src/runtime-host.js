import {
  DEFAULT_DRIVER_CALL_TIMEOUT_MS,
  MAX_EFFECT_GRANTS,
  MAX_ORIGINS,
  MAX_OUTSTANDING_OPERATIONS,
  admitNewOperation,
  canonicalDigest,
  canonicalOrigin,
  digest,
  freezeResult,
  futureDeadline,
  indeterminateReceipt,
  parseEffectGrant,
  positiveInteger,
  reconciliationRequestDigest,
  requireRecord,
  stableId,
} from "./runtime-contract.js";
import { callWithDeadline, exclusive } from "./runtime-boundary.js";

export class BrowserProfileHost {
  #driver;
  #authority;
  #clock;
  #driverCallTimeoutMs;
  #profiles = new Map();
  #openingProfiles = new Set();
  #locks = new Map();

  constructor({ driver, authority, clock = () => Date.now(), driverCallTimeoutMs = DEFAULT_DRIVER_CALL_TIMEOUT_MS }) {
    requireRecord(driver, "driver");
    for (const method of ["start", "observe", "act", "reconcile", "stop"]) {
      if (typeof driver[method] !== "function") throw new TypeError(`driver.${method} must be a function`);
    }
    requireRecord(authority, "authority");
    if (typeof authority.verifyFinalUse !== "function") throw new TypeError("authority.verifyFinalUse must be a function");
    if (typeof clock !== "function") throw new TypeError("clock must be a function");
    positiveInteger(driverCallTimeoutMs, "driverCallTimeoutMs");
    this.#driver = driver;
    this.#authority = authority;
    this.#clock = clock;
    this.#driverCallTimeoutMs = driverCallTimeoutMs;
  }

  async openProfile(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return exclusive(this.#locks, profileId, async () => {
      if (this.#profiles.has(profileId) || this.#openingProfiles.has(profileId)) {
        throw new TypeError("profile is already open or opening");
      }
      this.#openingProfiles.add(profileId);
      try {
        const principalId = stableId(input.principalId, "principalId");
        const manifestDigest = digest(input.manifestDigest, "manifestDigest");
        const grantDigest = digest(input.grantDigest, "grantDigest");
        const generation = positiveInteger(input.generation, "generation");
        const expiresAtMs = futureDeadline(input.expiresAtMs, this.#clock(), "expiresAtMs");
        if (!Array.isArray(input.allowedOrigins) || input.allowedOrigins.length > MAX_ORIGINS) {
          throw new TypeError("allowedOrigins is not a bounded array");
        }
        const allowedOrigins = new Set(input.allowedOrigins.map(canonicalOrigin));
        if (allowedOrigins.size !== input.allowedOrigins.length) throw new TypeError("allowedOrigins contains duplicates");
        if (!Array.isArray(input.effectGrants) || input.effectGrants.length === 0 || input.effectGrants.length > MAX_EFFECT_GRANTS) {
          throw new TypeError("effectGrants must be a non-empty bounded array");
        }
        const effectGrants = new Map();
        for (const rawGrant of input.effectGrants) {
          const grant = parseEffectGrant(rawGrant, this.#clock(), allowedOrigins);
          if (effectGrants.has(grant.grantDigest)) throw new TypeError("effectGrants contains duplicate grantDigest");
          effectGrants.set(grant.grantDigest, grant);
        }
        const observed = requireRecord(await this.#callDriver("start", {
          profileId, principalId, manifestDigest, grantDigest, generation, allowedOrigins: [...allowedOrigins],
        }, expiresAtMs), "driver start observation");
        if (observed.started !== true) throw new TypeError("driver did not observe profile start");
        const processId = stableId(observed.processId, "processId");
        const state = {
          profileId, principalId, manifestDigest, grantDigest, generation, expiresAtMs, processId,
          pageGeneration: 0, documentDigest: null, allowedOrigins, effectGrants, operations: new Map(),
        };
        this.#profiles.set(profileId, state);
        return freezeResult({
          kind: "BrowserSessionV1", profileId, principalId, processId, generation, manifestDigest,
          grantDigest, expiresAtMs, effectGrantCount: effectGrants.size,
        });
      } finally {
        this.#openingProfiles.delete(profileId);
      }
    });
  }

  async observePage(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return exclusive(this.#locks, profileId, async () => {
      const state = this.#profile(input, true);
      const observationBudget = positiveInteger(input.observationBudget, "observationBudget");
      if (observationBudget > 1_000_000) throw new TypeError("observationBudget exceeds profile limit");
      const observed = requireRecord(await this.#callDriver("observe", {
        profileId: state.profileId, processId: state.processId, generation: state.generation, observationBudget,
      }, state.expiresAtMs), "driver page observation");
      const pageGeneration = positiveInteger(observed.pageGeneration, "pageGeneration");
      if (pageGeneration <= state.pageGeneration) throw new TypeError("page generation did not advance");
      const documentDigest = digest(observed.documentDigest, "documentDigest");
      const origin = canonicalOrigin(observed.origin);
      const originAllowed = state.allowedOrigins.has(origin);
      state.pageGeneration = pageGeneration;
      state.documentDigest = originAllowed ? documentDigest : null;
      return freezeResult({
        kind: "PageObservationV1", profileId: state.profileId, processId: state.processId,
        profileGeneration: state.generation, pageGeneration, documentDigest, origin, originAllowed,
        quarantined: !originAllowed, terminalObserved: true,
      });
    });
  }

  async navigateOrAct(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return exclusive(this.#locks, profileId, async () => {
      const state = this.#profile(input, true);
      const { operationId, requestSemantics, requestDigest } = admitNewOperation(state, input, this.#clock());
      const prior = state.operations.get(operationId);
      if (prior) {
        if (prior.requestDigest !== requestDigest) throw new TypeError("operation identity was reused with changed semantics");
        return prior.receipt;
      }
      if (this.#activeOperationCount(state) >= MAX_OUTSTANDING_OPERATIONS) {
        throw new TypeError("profile operation capacity is exhausted");
      }

      const verified = requireRecord(await this.#callAuthority(
        Object.freeze({ ...requestSemantics, requestDigest }), requestSemantics.deadlineMs,
      ), "final-use authority observation");
      if (verified.authorized !== true) throw new TypeError("final-use authority was denied");
      const witnessDigest = digest(verified.witnessDigest, "verifiedUseTokenWitnessDigest");
      if (digest(verified.requestDigest, "verified requestDigest") !== requestDigest) {
        throw new TypeError("final-use authority did not bind the admitted request");
      }
      if (positiveInteger(verified.authorityEpoch, "verified authorityEpoch") !== requestSemantics.authorityEpoch) {
        throw new TypeError("final-use authority epoch changed before dispatch");
      }
      const semantics = Object.freeze({ ...requestSemantics, verifiedUseTokenWitnessDigest: witnessDigest });
      const semanticDigest = canonicalDigest(semantics);
      const entry = {
        requestDigest, semanticDigest, semantics, phase: "dispatching",
        receipt: indeterminateReceipt(state.profileId, operationId, semanticDigest, "dispatching"),
      };
      // Reserve identity before the first effectful await: retries can never redispatch it.
      state.operations.set(operationId, entry);
      try {
        const observed = requireRecord(await this.#callDriver("act", semantics, requestSemantics.deadlineMs), "driver effect observation");
        entry.receipt = this.#effectReceipt(state.profileId, operationId, semanticDigest, observed);
        entry.phase = entry.receipt.terminalObserved ? "terminal" : "indeterminate";
        return entry.receipt;
      } catch (error) {
        entry.phase = "indeterminate";
        entry.receipt = indeterminateReceipt(
          state.profileId, operationId, semanticDigest,
          error?.name === "BrowserDriverTimeoutError" ? "driver_timeout" : "driver_error_after_dispatch_boundary",
        );
        return entry.receipt;
      }
    });
  }

  async reconcileOperation(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return exclusive(this.#locks, profileId, async () => {
      const state = this.#profile(input, false);
      const operationId = stableId(input.operationId, "operationId");
      const prior = state.operations.get(operationId);
      if (!prior) throw new TypeError("operation has not crossed the browser effect boundary");
      if (prior.requestDigest !== reconciliationRequestDigest(state, input, prior.semantics)) {
        throw new TypeError("operation reconciliation changed immutable semantics");
      }
      if (prior.receipt.terminalObserved) return prior.receipt;
      try {
        const observed = requireRecord(await this.#callDriver(
          "reconcile", prior.semantics, this.#clock() + this.#driverCallTimeoutMs,
        ), "driver reconciliation observation");
        prior.receipt = this.#effectReceipt(state.profileId, operationId, prior.semanticDigest, observed);
        prior.phase = prior.receipt.terminalObserved ? "terminal" : "indeterminate";
      } catch (error) {
        prior.phase = "indeterminate";
        prior.receipt = indeterminateReceipt(
          state.profileId, operationId, prior.semanticDigest,
          error?.name === "BrowserDriverTimeoutError" ? "reconcile_timeout" : "reconcile_error",
        );
      }
      return prior.receipt;
    });
  }

  async closeProfile(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return exclusive(this.#locks, profileId, async () => {
      const state = this.#profile(input, false);
      if ([...state.operations.values()].some((entry) => !entry.receipt.terminalObserved)) {
        throw new TypeError("profile has indeterminate browser effects requiring reconciliation");
      }
      const observed = requireRecord(await this.#callDriver("stop", {
        profileId: state.profileId, processId: state.processId, generation: state.generation,
      }, this.#clock() + this.#driverCallTimeoutMs), "driver stop observation");
      if (observed.stopped !== true) throw new TypeError("driver did not observe profile stop");
      this.#profiles.delete(state.profileId);
      return freezeResult({
        kind: "BrowserProfileClosedV1", profileId: state.profileId, processId: state.processId,
        generation: state.generation, terminalObserved: true,
      });
    });
  }

  #profile(input, requireLiveGrant) {
    const profileId = stableId(input.profileId, "profileId");
    const state = this.#profiles.get(profileId);
    if (!state) throw new TypeError("profile is not open");
    if (input.principalId !== state.principalId) throw new TypeError("principal does not own the profile");
    if (input.generation !== state.generation) throw new TypeError("profile generation mismatch");
    if (requireLiveGrant && this.#clock() >= state.expiresAtMs) throw new TypeError("profile grant has expired");
    return state;
  }

  #activeOperationCount(state) {
    let count = 0;
    for (const entry of state.operations.values()) if (!entry.receipt.terminalObserved) count += 1;
    return count;
  }

  #effectReceipt(profileId, operationId, semanticDigest, observed) {
    if (observed.terminalObserved !== true) {
      return indeterminateReceipt(profileId, operationId, semanticDigest, "terminal_not_observed");
    }
    if (observed.status !== "succeeded" && observed.status !== "failed") {
      throw new TypeError("terminal browser status is not registered");
    }
    return freezeResult({
      kind: "BrowserEffectObservationV1", profileId, operationId, semanticDigest, status: observed.status,
      outcomeDigest: digest(observed.outcomeDigest, "outcomeDigest"), terminalObserved: true,
      observationReason: "terminal_observed",
    });
  }

  #callAuthority(payload, deadlineMs) {
    return callWithDeadline({
      call: (value) => this.#authority.verifyFinalUse(value), payload, now: this.#clock,
      deadlineMs, timeoutCapMs: this.#driverCallTimeoutMs, abortable: false, timeoutName: "browser authority",
    });
  }

  #callDriver(method, payload, deadlineMs) {
    return callWithDeadline({
      call: (value, context) => this.#driver[method](value, context), payload, now: this.#clock,
      deadlineMs, timeoutCapMs: this.#driverCallTimeoutMs, abortable: true, timeoutName: "browser driver",
    });
  }
}

import {
  DEFAULT_DRIVER_CALL_TIMEOUT_MS,
  DEFAULT_MAX_ACTIVE_PROFILES,
  MAX_CONFIGURED_ACTIVE_PROFILES,
  MAX_DRIVER_CALL_TIMEOUT_MS,
  MAX_EFFECT_GRANTS,
  MAX_ORIGINS,
  MAX_OUTSTANDING_OPERATIONS,
  MAX_RETAINED_TERMINAL_OPERATIONS,
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

const UTF8 = new TextEncoder();
const MAX_SEMANTIC_OBSERVATION_BYTES = 262_144;

function boundedSemanticObservation(value, observationBudget) {
  requireRecord(value, "semanticObservation");
  const encoded = JSON.stringify(value);
  const limit = Math.min(observationBudget, MAX_SEMANTIC_OBSERVATION_BYTES);
  if (UTF8.encode(encoded).byteLength > limit) {
    throw new TypeError(
      "semanticObservation exceeds the admitted observation budget",
    );
  }
  return Object.freeze(JSON.parse(encoded));
}

export class BrowserProfileHost {
  #driver;
  #authority;
  #journal;
  #clock;
  #driverCallTimeoutMs;
  #maxActiveProfiles;
  #maxOutstandingOperations;
  #profiles = new Map();
  #openingProfiles = new Set();
  #locks = new Map();

  constructor({
    driver,
    authority,
    journal,
    clock = () => Date.now(),
    driverCallTimeoutMs = DEFAULT_DRIVER_CALL_TIMEOUT_MS,
    maxActiveProfiles = DEFAULT_MAX_ACTIVE_PROFILES,
    allowVolatileJournalForTests = false,
  }) {
    requireRecord(driver, "driver");
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
        throw new TypeError(`driver.${method} must be a function`);
      }
    }
    if (driver.supportsAbort !== true) {
      throw new TypeError("driver must declare supportsAbort=true");
    }
    requireRecord(authority, "authority");
    if (typeof authority.withVerifiedUse !== "function") {
      throw new TypeError("authority.withVerifiedUse must be a function");
    }
    requireRecord(journal, "journal");
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
    if (typeof allowVolatileJournalForTests !== "boolean") {
      throw new TypeError("allowVolatileJournalForTests must be boolean");
    }
    if (journal.durable !== true && allowVolatileJournalForTests !== true) {
      throw new TypeError(
        "browser effect owner requires a durable operation journal",
      );
    }
    const driverOutstandingLimit =
      driver.maxOutstandingOperations ?? MAX_OUTSTANDING_OPERATIONS;
    positiveInteger(driverOutstandingLimit, "driver.maxOutstandingOperations");
    if (driverOutstandingLimit > MAX_OUTSTANDING_OPERATIONS) {
      throw new TypeError(
        "driver.maxOutstandingOperations exceeds Browser hard ceiling",
      );
    }
    if (typeof clock !== "function") {
      throw new TypeError("clock must be a function");
    }
    positiveInteger(driverCallTimeoutMs, "driverCallTimeoutMs");
    if (driverCallTimeoutMs > MAX_DRIVER_CALL_TIMEOUT_MS) {
      throw new TypeError(
        "driverCallTimeoutMs exceeds the Browser hard ceiling",
      );
    }
    positiveInteger(maxActiveProfiles, "maxActiveProfiles");
    if (maxActiveProfiles > MAX_CONFIGURED_ACTIVE_PROFILES) {
      throw new TypeError(
        "maxActiveProfiles exceeds the configured Browser process ceiling",
      );
    }
    this.#driver = driver;
    this.#authority = authority;
    this.#journal = journal;
    this.#clock = clock;
    this.#driverCallTimeoutMs = driverCallTimeoutMs;
    this.#maxActiveProfiles = maxActiveProfiles;
    this.#maxOutstandingOperations = driverOutstandingLimit;
  }

  async openProfile(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return exclusive(this.#locks, profileId, async () => {
      if (this.#profiles.has(profileId) || this.#openingProfiles.has(profileId)) {
        throw new TypeError("profile is already open or opening");
      }
      if (
        this.#profiles.size + this.#openingProfiles.size >=
        this.#maxActiveProfiles
      ) {
        const error = new Error("browser active profile capacity is exhausted");
        error.name = "BrowserBackpressureError";
        error.code = "BROWSER_PROFILE_CAPACITY";
        throw error;
      }
      this.#openingProfiles.add(profileId);
      try {
        const principalId = stableId(input.principalId, "principalId");
        const manifestDigest = digest(input.manifestDigest, "manifestDigest");
        const grantDigest = digest(input.grantDigest, "grantDigest");
        const generation = positiveInteger(input.generation, "generation");
        await this.#journal.assertProfileGenerationAvailable(
          profileId,
          generation,
        );
        const expiresAtMs = futureDeadline(
          input.expiresAtMs,
          this.#clock(),
          "expiresAtMs",
        );
        if (
          !Array.isArray(input.allowedOrigins) ||
          input.allowedOrigins.length > MAX_ORIGINS
        ) {
          throw new TypeError("allowedOrigins is not a bounded array");
        }
        const allowedOrigins = new Set(input.allowedOrigins.map(canonicalOrigin));
        if (allowedOrigins.size !== input.allowedOrigins.length) {
          throw new TypeError("allowedOrigins contains duplicates");
        }
        if (
          !Array.isArray(input.effectGrants) ||
          input.effectGrants.length > MAX_EFFECT_GRANTS
        ) {
          throw new TypeError("effectGrants must be a bounded array");
        }
        const effectGrants = new Map();
        for (const rawGrant of input.effectGrants) {
          const grant = parseEffectGrant(
            rawGrant,
            this.#clock(),
            allowedOrigins,
          );
          if (effectGrants.has(grant.grantDigest)) {
            throw new TypeError("effectGrants contains duplicate grantDigest");
          }
          effectGrants.set(grant.grantDigest, grant);
        }
        const observed = requireRecord(
          await this.#callDriver(
            "start",
            {
              profileId,
              principalId,
              manifestDigest,
              grantDigest,
              generation,
              allowedOrigins: [...allowedOrigins],
            },
            expiresAtMs,
          ),
          "driver start observation",
        );
        if (observed.started !== true) {
          throw new TypeError("driver did not observe profile start");
        }
        const processId = stableId(observed.processId, "processId");
        const profileOwnerDigest = digest(
          observed.profileOwnerDigest,
          "profileOwnerDigest",
        );
        const state = {
          profileId,
          principalId,
          manifestDigest,
          grantDigest,
          generation,
          expiresAtMs,
          processId,
          profileOwnerDigest,
          pageGeneration: 0,
          documentDigest: null,
          quarantined: false,
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
          profileOwnerDigest,
          expiresAtMs,
          effectGrantCount: effectGrants.size,
        });
      } finally {
        this.#openingProfiles.delete(profileId);
      }
    });
  }

  async admitEffectGrant(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return exclusive(this.#locks, profileId, async () => {
      const state = this.#profile(input, true);
      const grant = parseEffectGrant(
        input.effectGrant,
        this.#clock(),
        state.allowedOrigins,
      );
      const prior = state.effectGrants.get(grant.grantDigest);
      if (prior && canonicalDigest(prior) !== canonicalDigest(grant)) {
        throw new TypeError(
          "effect grant identity was reused with changed semantics",
        );
      }
      if (!prior && state.effectGrants.size >= MAX_EFFECT_GRANTS) {
        throw new TypeError("profile effect grant capacity is exhausted");
      }
      state.effectGrants.set(grant.grantDigest, grant);
      return freezeResult({
        kind: "BrowserEffectGrantAdmittedV1",
        profileId: state.profileId,
        generation: state.generation,
        effectGrantDigest: grant.grantDigest,
        effectGrantCount: state.effectGrants.size,
      });
    });
  }

  async observePage(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return exclusive(this.#locks, profileId, async () => {
      const state = this.#profile(input, true);
      const observationBudget = positiveInteger(
        input.observationBudget,
        "observationBudget",
      );
      if (observationBudget > 1_000_000) {
        throw new TypeError("observationBudget exceeds profile limit");
      }
      const observed = requireRecord(
        await this.#callDriver(
          "observe",
          {
            profileId: state.profileId,
            processId: state.processId,
            generation: state.generation,
            observationBudget,
          },
          state.expiresAtMs,
        ),
        "driver page observation",
      );
      const pageGeneration = positiveInteger(
        observed.pageGeneration,
        "pageGeneration",
      );
      if (pageGeneration <= state.pageGeneration) {
        throw new TypeError("page generation did not advance");
      }
      const semanticObservation = boundedSemanticObservation(
        observed.semanticObservation,
        observationBudget,
      );
      const semanticDigest = digest(observed.semanticDigest, "semanticDigest");
      if (canonicalDigest(semanticObservation) !== semanticDigest) {
        throw new TypeError("semantic observation digest mismatch");
      }
      const documentDigest = digest(observed.documentDigest, "documentDigest");
      const origin = canonicalOrigin(observed.origin);
      const originAllowed = state.allowedOrigins.has(origin);
      state.pageGeneration = pageGeneration;
      state.documentDigest = originAllowed ? documentDigest : null;
      if (!originAllowed) {
        state.quarantined = true;
        const contained = requireRecord(
          await this.#callDriver(
            "contain",
            {
              profileId: state.profileId,
              processId: state.processId,
              generation: state.generation,
              reason: "origin_escape",
            },
            this.#clock() + this.#driverCallTimeoutMs,
          ),
          "driver containment observation",
        );
        if (contained.contained !== true) {
          throw new TypeError("driver did not observe profile containment");
        }
      }
      return freezeResult({
        kind: "PageObservationV1",
        profileId: state.profileId,
        processId: state.processId,
        profileGeneration: state.generation,
        pageGeneration,
        documentDigest,
        semanticDigest,
        semanticObservation,
        origin,
        originAllowed,
        quarantined: !originAllowed,
        terminalObserved: true,
      });
    });
  }

  async navigateOrAct(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return exclusive(this.#locks, profileId, async () => {
      // Existing operation identities are observations/replays, not new
      // authority. Resolve them before enforcing current lease/quarantine so a
      // retry after expiry cannot become either a redispatch or an opaque
      // "grant expired" failure.
      const state = this.#profile(input, false);
      const operationId = stableId(input.operationId, "operationId");
      let prior = state.operations.get(operationId);
      if (!prior) {
        const durable = await this.#journal.getOperation(
          state.profileId,
          state.generation,
          operationId,
        );
        if (durable) {
          const replaySemantics = this.#requestSemanticsFromDurableInput(
            state,
            input,
            durable,
          );
          prior = this.#entryFromDurable(durable, replaySemantics);
        }
      }
      if (prior) {
        const replayRequestDigest = reconciliationRequestDigest(
          state,
          input,
          prior.semantics,
        );
        if (prior.requestDigest !== replayRequestDigest) {
          throw new TypeError(
            "operation identity was reused with changed semantics",
          );
        }
        if (!state.operations.has(operationId) && !prior.receipt.terminalObserved) {
          state.operations.set(operationId, prior);
        }
        return prior.receipt;
      }

      // Only a genuinely new effect requires the current live profile grant
      // and non-quarantined state.
      this.#profile(input, true);
      const admitted = admitNewOperation(state, input, this.#clock());
      const { requestSemantics, requestDigest } = admitted;
      if (admitted.operationId !== operationId) {
        throw new TypeError("admitted operation identity changed");
      }
      if (this.#activeOperationCount(state) >= this.#maxOutstandingOperations) {
        throw new TypeError("profile operation capacity is exhausted");
      }

      let entry = null;
      try {
        const observed = requireRecord(
          await this.#withVerifiedUse(
            Object.freeze({ ...requestSemantics, requestDigest }),
            requestSemantics.deadlineMs,
            async (verified) => {
              requireRecord(verified, "verified-use witness");
              if (verified.authorized !== true) {
                throw new TypeError("final-use authority was denied");
              }
              const witnessDigest = digest(
                verified.witnessDigest,
                "verifiedUseTokenWitnessDigest",
              );
              if (
                digest(verified.requestDigest, "verified requestDigest") !==
                requestDigest
              ) {
                throw new TypeError(
                  "final-use authority did not bind the admitted request",
                );
              }
              if (
                positiveInteger(
                  verified.authorityEpoch,
                  "verified authorityEpoch",
                ) !== requestSemantics.authorityEpoch
              ) {
                throw new TypeError(
                  "final-use authority epoch changed before dispatch",
                );
              }
              const semantics = Object.freeze({
                ...requestSemantics,
                verifiedUseTokenWitnessDigest: witnessDigest,
              });
              const semanticDigest = canonicalDigest(semantics);
              entry = {
                requestDigest,
                semanticDigest,
                semantics,
                phase: "dispatching",
                receipt: indeterminateReceipt(
                  state.profileId,
                  operationId,
                  semanticDigest,
                  "dispatching",
                ),
              };
              await this.#journal.recordDispatch(this.#durableRecord(state, entry));
              state.operations.set(operationId, entry);
              try {
                const dispatchObservation = await this.#callDriver(
                  "dispatch",
                  semantics,
                  requestSemantics.deadlineMs,
                );
                state.documentDigest = null;
                return dispatchObservation;
              } catch (error) {
                if (error?.code !== "BROWSER_WORKER_PRE_DISPATCH_REJECTED") {
                  state.documentDigest = null;
                }
                throw error;
              }
            },
          ),
          "driver dispatch observation",
        );
        entry.receipt = this.#effectReceipt(
          state.profileId,
          operationId,
          entry.semanticDigest,
          observed,
        );
        entry.phase = entry.receipt.terminalObserved ? "terminal" : "indeterminate";
      } catch (error) {
        if (!entry) throw error;
        if (
          error?.code === "BROWSER_WORKER_PRE_DISPATCH_REJECTED" &&
          typeof error?.outcomeDigest === "string"
        ) {
          entry.phase = "terminal";
          entry.receipt = freezeResult({
            ...this.#effectReceipt(
              state.profileId,
              operationId,
              entry.semanticDigest,
              {
                terminalObserved: true,
                status: "failed",
                outcomeDigest: error.outcomeDigest,
              },
            ),
            observationReason: "worker_rejected_before_dispatch",
          });
        } else {
          entry.phase = "indeterminate";
          entry.receipt = indeterminateReceipt(
            state.profileId,
            operationId,
            entry.semanticDigest,
            error?.name === "BrowserDriverTimeoutError"
              ? "driver_timeout"
              : "driver_error_after_dispatch_boundary",
          );
        }
      }
      await this.#persistReceipt(state, entry);
      this.#pruneTerminalOperations(state);
      return entry.receipt;
    });
  }

  async reconcileOperation(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return exclusive(this.#locks, profileId, async () => {
      const state = this.#profile(input, false);
      const operationId = stableId(input.operationId, "operationId");
      let prior = state.operations.get(operationId);
      if (!prior) {
        const durable = await this.#journal.getOperation(
          state.profileId,
          state.generation,
          operationId,
        );
        if (!durable) {
          throw new TypeError(
            "operation has not crossed the browser effect boundary",
          );
        }
        prior = this.#entryFromDurable(
          durable,
          this.#requestSemanticsFromDurableInput(state, input, durable),
        );
        if (!prior.receipt.terminalObserved) {
          state.operations.set(operationId, prior);
        }
      }
      if (
        prior.requestDigest !==
        reconciliationRequestDigest(state, input, prior.semantics)
      ) {
        throw new TypeError(
          "operation reconciliation changed immutable semantics",
        );
      }
      if (prior.receipt.terminalObserved) return prior.receipt;
      try {
        const observed = requireRecord(
          await this.#callDriver(
            "reconcile",
            prior.semantics,
            this.#clock() + this.#driverCallTimeoutMs,
          ),
          "driver reconciliation observation",
        );
        prior.receipt = this.#effectReceipt(
          state.profileId,
          operationId,
          prior.semanticDigest,
          observed,
        );
        prior.phase = prior.receipt.terminalObserved ? "terminal" : "indeterminate";
      } catch (error) {
        prior.phase = "indeterminate";
        prior.receipt = indeterminateReceipt(
          state.profileId,
          operationId,
          prior.semanticDigest,
          error?.name === "BrowserDriverTimeoutError"
            ? "reconcile_timeout"
            : "reconcile_error",
        );
      }
      await this.#persistReceipt(state, prior);
      this.#pruneTerminalOperations(state);
      return prior.receipt;
    });
  }

  async reconcilePersistedOperation(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    const generation = positiveInteger(input.generation, "generation");
    const operationId = stableId(input.operationId, "operationId");
    return exclusive(this.#locks, `${profileId}:${generation}`, async () => {
      const durable = await this.#journal.getOperation(
        profileId,
        generation,
        operationId,
      );
      if (!durable) throw new TypeError("persisted operation does not exist");
      if (input.principalId !== durable.principalId) {
        throw new TypeError("principal does not own persisted operation");
      }
      const pseudoState = {
        profileId: durable.profileId,
        principalId: durable.principalId,
        processId: durable.processId,
        generation: durable.generation,
        grantDigest: durable.profileGrantDigest,
      };
      const semantics = this.#requestSemanticsFromDurableInput(
        pseudoState,
        input,
        durable,
      );
      const requestDigest = canonicalDigest(semantics);
      if (requestDigest !== durable.requestDigest) {
        throw new TypeError(
          "persisted reconciliation changed immutable semantics",
        );
      }
      if (durable.terminalObserved === true) {
        const receipt = this.#receiptFromDurable(durable);
        await this.#retireRecoveredGenerationIfTerminal(profileId, generation);
        return receipt;
      }
      const effectSemantics = Object.freeze({
        ...semantics,
        verifiedUseTokenWitnessDigest: durable.verifiedUseTokenWitnessDigest,
      });
      if (canonicalDigest(effectSemantics) !== durable.semanticDigest) {
        throw new TypeError("persisted semantic digest mismatch");
      }
      let receipt;
      try {
        const observed = requireRecord(
          await this.#callDriver(
            "reconcilePersisted",
            effectSemantics,
            this.#clock() + this.#driverCallTimeoutMs,
          ),
          "persisted driver reconciliation observation",
        );
        receipt = this.#effectReceipt(
          profileId,
          operationId,
          durable.semanticDigest,
          observed,
        );
      } catch (error) {
        receipt = indeterminateReceipt(
          profileId,
          operationId,
          durable.semanticDigest,
          error?.name === "BrowserDriverTimeoutError"
            ? "persisted_reconcile_timeout"
            : "persisted_reconcile_error",
        );
      }
      await this.#journal.recordObservation({
        ...durable,
        status: receipt.status,
        outcomeDigest: receipt.outcomeDigest,
        terminalObserved: receipt.terminalObserved,
        observationReason: receipt.observationReason,
      });
      if (receipt.terminalObserved) {
        await this.#retireRecoveredGenerationIfTerminal(profileId, generation);
      }
      return receipt;
    });
  }

  async closeProfile(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return exclusive(this.#locks, profileId, async () => {
      const state = this.#profile(input, false);
      const durable = await this.#journal.listOperations(
        state.profileId,
        state.generation,
      );
      if (
        durable.some((entry) => entry.terminalObserved !== true) ||
        [...state.operations.values()].some(
          (entry) => !entry.receipt.terminalObserved,
        )
      ) {
        throw new TypeError(
          "profile has indeterminate browser effects requiring reconciliation",
        );
      }
      const observed = requireRecord(
        await this.#callDriver(
          "stop",
          {
            profileId: state.profileId,
            processId: state.processId,
            generation: state.generation,
          },
          this.#clock() + this.#driverCallTimeoutMs,
        ),
        "driver stop observation",
      );
      if (observed.stopped !== true) {
        throw new TypeError("driver did not observe profile stop");
      }
      this.#profiles.delete(state.profileId);
      try {
        await this.#journal.retireProfile(state.profileId, state.generation);
      } catch (cause) {
        const error = new Error(
          "browser profile stopped but durable journal retirement failed",
          { cause },
        );
        error.name = "BrowserJournalRetirementError";
        throw error;
      }
      return freezeResult({
        kind: "BrowserProfileClosedV1",
        profileId: state.profileId,
        processId: state.processId,
        generation: state.generation,
        terminalObserved: true,
      });
    });
  }

  async #retireRecoveredGenerationIfTerminal(profileId, generation) {
    const records = await this.#journal.listOperations(profileId, generation);
    if (
      records.length === 0 ||
      records.some((record) => record.terminalObserved !== true)
    ) {
      return;
    }
    try {
      await this.#journal.retireProfile(profileId, generation);
    } catch (cause) {
      const error = new Error(
        "recovered browser generation became terminal but journal retirement failed",
        { cause },
      );
      error.name = "BrowserJournalRetirementError";
      throw error;
    }
  }

  #profile(input, requireLiveGrant) {
    const profileId = stableId(input.profileId, "profileId");
    const state = this.#profiles.get(profileId);
    if (!state) throw new TypeError("profile is not open");
    if (input.principalId !== state.principalId) {
      throw new TypeError("principal does not own the profile");
    }
    if (input.generation !== state.generation) {
      throw new TypeError("profile generation mismatch");
    }
    if (requireLiveGrant && this.#clock() >= state.expiresAtMs) {
      throw new TypeError("profile grant has expired");
    }
    if (requireLiveGrant && state.quarantined) {
      throw new TypeError("profile is quarantined");
    }
    return state;
  }

  #activeOperationCount(state) {
    let count = 0;
    for (const entry of state.operations.values()) {
      if (!entry.receipt.terminalObserved) count += 1;
    }
    return count;
  }

  #pruneTerminalOperations(state) {
    const terminal = [...state.operations.entries()].filter(
      ([, entry]) => entry.receipt.terminalObserved,
    );
    while (terminal.length > MAX_RETAINED_TERMINAL_OPERATIONS) {
      const [operationId] = terminal.shift();
      state.operations.delete(operationId);
    }
  }

  #effectReceipt(profileId, operationId, semanticDigest, observed) {
    if (observed.terminalObserved !== true) {
      return indeterminateReceipt(
        profileId,
        operationId,
        semanticDigest,
        "terminal_not_observed",
      );
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
      observationReason: "terminal_observed",
    });
  }

  #durableRecord(state, entry) {
    const semantics = entry.semantics;
    return Object.freeze({
      profileId: state.profileId,
      principalId: state.principalId,
      generation: state.generation,
      operationId: semantics.operationId,
      requestDigest: entry.requestDigest,
      semanticDigest: entry.semanticDigest,
      processId: semantics.processId,
      pageGeneration: semantics.pageGeneration,
      documentDigest: semantics.documentDigest,
      action: semantics.action,
      destinationOrigin: semantics.destinationOrigin,
      finalPayloadDigest: semantics.finalPayloadDigest,
      profileGrantDigest: semantics.profileGrantDigest,
      effectGrantDigest: semantics.effectGrantDigest,
      authorityEpoch: semantics.authorityEpoch,
      deadlineMs: semantics.deadlineMs,
      verifiedUseTokenWitnessDigest: semantics.verifiedUseTokenWitnessDigest,
      status: entry.receipt.status,
      outcomeDigest: entry.receipt.outcomeDigest,
      terminalObserved: entry.receipt.terminalObserved,
      observationReason: entry.receipt.observationReason,
    });
  }

  async #persistReceipt(state, entry) {
    try {
      await this.#journal.recordObservation(this.#durableRecord(state, entry));
    } catch {
      entry.phase = "indeterminate";
      entry.receipt = indeterminateReceipt(
        state.profileId,
        entry.semantics.operationId,
        entry.semanticDigest,
        "journal_observation_write_failed",
      );
    }
  }

  #entryFromDurable(durable, requestSemantics) {
    const semantics = Object.freeze({
      ...requestSemantics,
      verifiedUseTokenWitnessDigest: durable.verifiedUseTokenWitnessDigest,
    });
    if (canonicalDigest(semantics) !== durable.semanticDigest) {
      throw new TypeError("durable operation semantic digest mismatch");
    }
    return {
      requestDigest: durable.requestDigest,
      semanticDigest: durable.semanticDigest,
      semantics,
      phase: durable.terminalObserved ? "terminal" : "indeterminate",
      receipt: this.#receiptFromDurable(durable),
    };
  }

  #receiptFromDurable(durable) {
    return freezeResult({
      kind: "BrowserEffectObservationV1",
      profileId: durable.profileId,
      operationId: durable.operationId,
      semanticDigest: durable.semanticDigest,
      status: durable.status,
      outcomeDigest: durable.outcomeDigest ?? null,
      terminalObserved: durable.terminalObserved === true,
      observationReason: durable.observationReason ?? "durable_observation",
    });
  }

  #requestSemanticsFromDurableInput(state, input, durable) {
    const typedState = {
      ...state,
      pageGeneration: durable.pageGeneration,
      documentDigest: durable.documentDigest,
      allowedOrigins: new Set([durable.destinationOrigin]),
      effectGrants: new Map([
        [
          durable.effectGrantDigest,
          {
            grantDigest: durable.effectGrantDigest,
            action: durable.action,
            destinationOrigin: durable.destinationOrigin,
            finalPayloadDigest: durable.finalPayloadDigest,
            authorityEpoch: durable.authorityEpoch,
            expiresAtMs: Number.MAX_SAFE_INTEGER,
          },
        ],
      ]),
    };
    const normalizedInput = { ...input, deadlineMs: Number.MAX_SAFE_INTEGER };
    const admitted = admitNewOperation(typedState, normalizedInput, 1);
    return Object.freeze({
      ...admitted.requestSemantics,
      deadlineMs: durable.deadlineMs,
    });
  }

  #withVerifiedUse(request, deadlineMs, consumer) {
    futureDeadline(deadlineMs, this.#clock(), "deadlineMs");
    return this.#authority.withVerifiedUse(request, (witness) => {
      // Authority can wait for a revocation fence before entering the consumer.
      // Re-check Browser's operation deadline at the exact fenced boundary so a
      // delayed authority handoff cannot authorize a stale effect.
      futureDeadline(deadlineMs, this.#clock(), "deadlineMs");
      return consumer(witness);
    });
  }
  #callDriver(method, payload, deadlineMs) {
    return callWithDeadline({
      call: (value, context) => this.#driver[method](value, context),
      payload,
      now: this.#clock,
      deadlineMs,
      timeoutCapMs: this.#driverCallTimeoutMs,
      abortable: true,
      timeoutName: "browser driver",
    });
  }
}

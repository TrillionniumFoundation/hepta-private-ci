import {
  DEFAULT_DRIVER_CALL_TIMEOUT_MS,
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

export class BrowserProfileHost {
  #driver;
  #authority;
  #journal;
  #clock;
  #driverCallTimeoutMs;
  #profiles = new Map();
  #openingProfiles = new Set();
  #locks = new Map();

  constructor({
    driver,
    authority,
    journal,
    clock = () => Date.now(),
    driverCallTimeoutMs = DEFAULT_DRIVER_CALL_TIMEOUT_MS,
  }) {
    requireRecord(driver, "driver");
    for (const method of ["start", "observe", "dispatch", "reconcile", "stop"]) {
      if (typeof driver[method] !== "function") {
        throw new TypeError(`driver.${method} must be a function`);
      }
    }
    requireRecord(authority, "authority");
    if (typeof authority.withVerifiedUse !== "function") {
      throw new TypeError("authority.withVerifiedUse must be a function");
    }
    requireRecord(journal, "journal");
    for (const method of ["recordDispatch", "recordObservation", "getOperation", "listOperations"]) {
      if (typeof journal[method] !== "function") {
        throw new TypeError(`journal.${method} must be a function`);
      }
    }
    if (typeof clock !== "function") throw new TypeError("clock must be a function");
    positiveInteger(driverCallTimeoutMs, "driverCallTimeoutMs");
    this.#driver = driver;
    this.#authority = authority;
    this.#journal = journal;
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
        if (allowedOrigins.size !== input.allowedOrigins.length) {
          throw new TypeError("allowedOrigins contains duplicates");
        }
        if (!Array.isArray(input.effectGrants) || input.effectGrants.length > MAX_EFFECT_GRANTS) {
          throw new TypeError("effectGrants must be a bounded array");
        }
        const effectGrants = new Map();
        for (const rawGrant of input.effectGrants) {
          const grant = parseEffectGrant(rawGrant, this.#clock(), allowedOrigins);
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
        if (observed.started !== true) throw new TypeError("driver did not observe profile start");
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
      const grant = parseEffectGrant(input.effectGrant, this.#clock(), state.allowedOrigins);
      const prior = state.effectGrants.get(grant.grantDigest);
      if (prior && canonicalDigest(prior) !== canonicalDigest(grant)) {
        throw new TypeError("effect grant identity was reused with changed semantics");
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
      const observationBudget = positiveInteger(input.observationBudget, "observationBudget");
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
      const pageGeneration = positiveInteger(observed.pageGeneration, "pageGeneration");
      if (pageGeneration <= state.pageGeneration) {
        throw new TypeError("page generation did not advance");
      }
      const documentDigest = digest(observed.documentDigest, "documentDigest");
      const origin = canonicalOrigin(observed.origin);
      const originAllowed = state.allowedOrigins.has(origin);
      state.pageGeneration = pageGeneration;
      state.documentDigest = originAllowed ? documentDigest : null;
      return freezeResult({
        kind: "PageObservationV1",
        profileId: state.profileId,
        processId: state.processId,
        profileGeneration: state.generation,
        pageGeneration,
        documentDigest,
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
      const state = this.#profile(input, true);
      const { operationId, requestSemantics, requestDigest } = admitNewOperation(
        state,
        input,
        this.#clock(),
      );
      let prior = state.operations.get(operationId);
      if (!prior) {
        const durable = await this.#journal.getOperation(
          state.profileId,
          state.generation,
          operationId,
        );
        if (durable) prior = this.#entryFromDurable(durable, requestSemantics);
      }
      if (prior) {
        if (prior.requestDigest !== requestDigest) {
          throw new TypeError("operation identity was reused with changed semantics");
        }
        if (!state.operations.has(operationId) && !prior.receipt.terminalObserved) {
          state.operations.set(operationId, prior);
        }
        return prior.receipt;
      }
      if (this.#activeOperationCount(state) >= MAX_OUTSTANDING_OPERATIONS) {
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
              if (digest(verified.requestDigest, "verified requestDigest") !== requestDigest) {
                throw new TypeError("final-use authority did not bind the admitted request");
              }
              if (
                positiveInteger(verified.authorityEpoch, "verified authorityEpoch") !==
                requestSemantics.authorityEpoch
              ) {
                throw new TypeError("final-use authority epoch changed before dispatch");
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
              // This fsync and the local worker dispatch execute inside the
              // final-use fence. A successful revocation update therefore
              // cannot slip between final validation and effect dispatch.
              await this.#journal.recordDispatch(this.#durableRecord(state, entry));
              state.operations.set(operationId, entry);
              return this.#callDriver("dispatch", semantics, requestSemantics.deadlineMs);
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
          throw new TypeError("operation has not crossed the browser effect boundary");
        }
        prior = this.#entryFromDurable(
          durable,
          this.#requestSemanticsFromDurableInput(state, input, durable),
        );
        if (!prior.receipt.terminalObserved) state.operations.set(operationId, prior);
      }
      if (prior.requestDigest !== reconciliationRequestDigest(state, input, prior.semantics)) {
        throw new TypeError("operation reconciliation changed immutable semantics");
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
      const durable = await this.#journal.getOperation(profileId, generation, operationId);
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
        throw new TypeError("persisted reconciliation changed immutable semantics");
      }
      if (durable.terminalObserved === true) return this.#receiptFromDurable(durable);
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
            "reconcile",
            effectSemantics,
            this.#clock() + this.#driverCallTimeoutMs,
          ),
          "driver reconciliation observation",
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
            ? "reconcile_timeout"
            : "reconcile_error",
        );
      }
      await this.#journal.recordObservation({ ...durable, ...receipt });
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
        [...state.operations.values()].some((entry) => !entry.receipt.terminalObserved)
      ) {
        throw new TypeError("profile has indeterminate browser effects requiring reconciliation");
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
      if (observed.stopped !== true) throw new TypeError("driver did not observe profile stop");
      this.#profiles.delete(state.profileId);
      return freezeResult({
        kind: "BrowserProfileClosedV1",
        profileId: state.profileId,
        processId: state.processId,
        generation: state.generation,
        terminalObserved: true,
      });
    });
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
    return Object.freeze({ ...admitted.requestSemantics, deadlineMs: durable.deadlineMs });
  }

  async #withVerifiedUse(request, deadlineMs, consumer) {
    let enter;
    const entered = new Promise((resolve) => { enter = resolve; });
    let finishConsumer;
    const consumerFinished = new Promise((resolve) => { finishConsumer = resolve; });
    let enteredOnce = false;

    const authorityCall = Promise.resolve().then(() =>
      this.#authority.withVerifiedUse(request, async (verified) => {
        if (enteredOnce) {
          throw new TypeError("final-use authority invoked the consumer more than once");
        }
        enteredOnce = true;
        enter();
        try {
          return await consumer(verified);
        } finally {
          finishConsumer();
        }
      }),
    );
    // Phase one bounds only authority verification and entry. Once the
    // verified-use consumer has started, its driver operation owns its own
    // deadline; racing a second authority timer here can misclassify a driver
    // timeout as an authority failure.
    const first = await callWithDeadline({
      call: () =>
        Promise.race([
          authorityCall.then((value) => ({ kind: "completed", value })),
          entered.then(() => ({ kind: "entered" })),
        ]),
      payload: null,
      now: this.#clock,
      deadlineMs,
      timeoutCapMs: this.#driverCallTimeoutMs,
      abortable: false,
      timeoutName: "browser authority",
    });
    if (first.kind === "completed") return first.value;

    await consumerFinished;
    // After the local consumer settles, bound only the authority-side
    // completion/dispatch-boundary acknowledgement. An already-settled
    // consumer error (including BrowserDriverTimeoutError) wins immediately.
    return callWithDeadline({
      call: () => authorityCall,
      payload: null,
      now: this.#clock,
      deadlineMs,
      timeoutCapMs: this.#driverCallTimeoutMs,
      abortable: false,
      timeoutName: "browser authority",
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

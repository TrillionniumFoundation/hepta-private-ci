import {
  DEFAULT_DRIVER_TIMEOUT_MS,
  MAX_ACTIVE_OPERATIONS,
  MAX_EFFECT_GRANTS,
  MAX_ORIGINS,
  MAX_RETIRED_OPERATIONS,
  assertAuthority,
  assertDriver,
  assertStore,
  browserTypedActionDigest,
  canonicalOrigin,
  deadline,
  digest,
  freezeResult,
  parseEffectGrant,
  positiveInteger,
  requireRecord,
  stableId,
} from "./runtime-primitives.js";
import {
  admitOperation,
  assertReplayMatches,
  compactTerminalOperations,
  finalUseBinding,
} from "./runtime-operation.js";
import {
  activeOperationCount,
  decodeState,
  effectReceipt,
  encodeState,
  indeterminateReceipt,
} from "./runtime-state.js";
import {
  ProfileLockTable,
  callDriver,
  driverDeadline,
  recoveryDeadline,
} from "./runtime-support.js";

export { browserTypedActionDigest };

export class BrowserProfileHost {
  #driver;
  #authority;
  #store;
  #clock;
  #defaultDriverTimeoutMs;
  #profiles = new Map();
  #locks = new ProfileLockTable();

  constructor({
    driver,
    authority,
    store,
    clock = () => Date.now(),
    defaultDriverTimeoutMs = DEFAULT_DRIVER_TIMEOUT_MS,
    allowVolatileStore = false,
  }) {
    this.#driver = assertDriver(driver);
    this.#authority = assertAuthority(authority);
    this.#store = assertStore(store, allowVolatileStore);
    if (typeof clock !== "function") throw new TypeError("clock must be a function");
    this.#clock = clock;
    this.#defaultDriverTimeoutMs = positiveInteger(defaultDriverTimeoutMs, "defaultDriverTimeoutMs");
  }

  async listRecoverableProfiles() {
    return (await this.#store.listProfiles()).map((record) => ({
      profileId: record.profileId,
      principalId: record.principalId,
      generation: record.generation,
      lifecycle: record.lifecycle,
      pendingOperationCount: (record.operations ?? []).filter(
        (entry) => entry.receipt?.terminalObserved !== true,
      ).length,
    }));
  }

  async recoverProfile(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return this.#locks.run(profileId, async () => {
      if (this.#profiles.has(profileId)) return this.#sessionReceipt(this.#profiles.get(profileId), true);
      const persisted = await this.#store.loadProfile(profileId);
      if (!persisted) throw new TypeError("profile has no durable recovery state");
      const state = decodeState(persisted);
      if (input.principalId !== state.principalId || input.generation !== state.generation) {
        throw new TypeError("persisted profile identity mismatch");
      }
      this.#profiles.set(profileId, state);
      return this.#sessionReceipt(state, true);
    });
  }

  async openProfile(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return this.#locks.run(profileId, async () => {
      const now = this.#clock();
      const principalId = stableId(input.principalId, "principalId");
      const manifestDigest = digest(input.manifestDigest, "manifestDigest");
      const grantDigest = digest(input.grantDigest, "grantDigest");
      const generation = positiveInteger(input.generation, "generation");
      const expiresAtMs = deadline(input.expiresAtMs, now, "expiresAtMs");
      if (!Array.isArray(input.allowedOrigins) || input.allowedOrigins.length > MAX_ORIGINS) {
        throw new TypeError("allowedOrigins is not a bounded array");
      }
      const allowedOrigins = new Set(input.allowedOrigins.map(canonicalOrigin));
      if (allowedOrigins.size !== input.allowedOrigins.length) {
        throw new TypeError("allowedOrigins contains duplicates");
      }
      if (
        !Array.isArray(input.effectGrants)
        || input.effectGrants.length === 0
        || input.effectGrants.length > MAX_EFFECT_GRANTS
      ) {
        throw new TypeError("effectGrants must be a non-empty bounded array");
      }
      const effectGrants = new Map();
      for (const rawGrant of input.effectGrants) {
        const grant = parseEffectGrant(rawGrant, now, allowedOrigins);
        if (effectGrants.has(grant.grantDigest)) {
          throw new TypeError("effectGrants contains duplicate grantDigest");
        }
        effectGrants.set(grant.grantDigest, grant);
      }
      if (this.#profiles.has(profileId)) throw new TypeError("profile is already open");
      if (await this.#store.loadProfile(profileId)) {
        throw new TypeError("profile has durable state requiring recovery");
      }

      const state = {
        profileId,
        principalId,
        manifestDigest,
        grantDigest,
        generation,
        expiresAtMs,
        processId: null,
        lifecycle: "starting",
        pageGeneration: 0,
        documentDigest: null,
        origin: null,
        quarantinedReason: null,
        allowedOrigins,
        effectGrants,
        operations: new Map(),
        retiredOperations: new Map(),
        nextOperationSequence: 1,
      };
      this.#profiles.set(profileId, state);
      await this.#persist(state);

      const startDeadlineMs = driverDeadline(
        this.#clock,
        this.#defaultDriverTimeoutMs,
        input.startDeadlineMs,
        expiresAtMs,
      );
      let observed;
      try {
        observed = requireRecord(
          await callDriver(this.#driver, this.#clock, "start", {
            profileId,
            principalId,
            manifestDigest,
            grantDigest,
            generation,
            allowedOrigins: [...allowedOrigins],
          }, startDeadlineMs),
          "driver start observation",
        );
      } catch (error) {
        state.lifecycle = "start_indeterminate";
        await this.#persist(state);
        throw error;
      }
      if (observed.started !== true) {
        this.#profiles.delete(profileId);
        await this.#store.deleteProfile(profileId);
        throw new TypeError("driver did not observe profile start");
      }
      state.processId = stableId(observed.processId, "processId");
      state.lifecycle = "open";
      await this.#persist(state);
      return this.#sessionReceipt(state, false);
    });
  }

  async observePage(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return this.#locks.run(profileId, async () => {
      const state = await this.#activeProfile(input);
      const observationBudget = positiveInteger(input.observationBudget, "observationBudget");
      if (observationBudget > 1_000_000) {
        throw new TypeError("observationBudget exceeds profile limit");
      }
      const observed = requireRecord(
        await callDriver(this.#driver, this.#clock, "observe", {
          profileId: state.profileId,
          processId: state.processId,
          generation: state.generation,
          observationBudget,
        }, driverDeadline(
          this.#clock,
          this.#defaultDriverTimeoutMs,
          input.deadlineMs,
          state.expiresAtMs,
        )),
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
      state.origin = origin;
      if (!state.allowedOrigins.has(origin)) {
        state.lifecycle = "quarantined";
        state.quarantinedReason = "observed_ungranted_origin";
        await this.#persist(state);
        throw new TypeError("observed origin is outside the profile grant; profile quarantined");
      }
      await this.#persist(state);
      return freezeResult({
        kind: "PageObservationV1",
        profileId: state.profileId,
        processId: state.processId,
        profileGeneration: state.generation,
        pageGeneration,
        documentDigest,
        origin,
        originAllowed: true,
        terminalObserved: true,
      });
    });
  }

  async navigateOrAct(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return this.#locks.run(profileId, async () => {
      const state = await this.#profileForIdentity(input);
      const operationId = stableId(input.operationId, "operationId");
      const prior = state.operations.get(operationId) ?? state.retiredOperations.get(operationId);
      if (prior) {
        assertReplayMatches(input, prior);
        return prior.receipt;
      }

      const admitted = admitOperation(input, state, this.#clock());
      const { semantics, semanticDigest, typedAction, grant } = admitted;
      if (activeOperationCount(state) >= MAX_ACTIVE_OPERATIONS) {
        throw new TypeError("profile active operation capacity is exhausted");
      }
      compactTerminalOperations(state);

      const binding = finalUseBinding(state, grant, semantics, semanticDigest);
      const token = await this.#authority.claim(binding);
      const unknown = indeterminateReceipt(state.profileId, operationId, semanticDigest);
      const entry = {
        sequence: state.nextOperationSequence,
        semanticDigest,
        semantics,
        receipt: unknown,
        phase: "dispatching",
      };
      state.nextOperationSequence += 1;
      state.operations.set(operationId, entry);
      await this.#persist(state);

      let effectBoundaryEntered = false;
      try {
        const observed = requireRecord(
          await this.#authority.withVerifiedUse(token, binding, async () => {
            const finalNow = this.#clock();
            if (
              finalNow >= state.expiresAtMs
              || finalNow >= grant.expiresAtMs
              || finalNow >= semantics.deadlineMs
            ) {
              throw new TypeError("browser effect authority expired before final dispatch");
            }
            effectBoundaryEntered = true;
            return callDriver(
              this.#driver,
              this.#clock,
              "act",
              { ...semantics, typedAction },
              semantics.deadlineMs,
            );
          }),
          "driver effect observation",
        );
        const terminal = effectReceipt(state.profileId, operationId, semanticDigest, observed);
        entry.receipt = terminal;
        entry.phase = terminal.terminalObserved ? "terminal" : "indeterminate";
        await this.#persist(state);
        return terminal;
      } catch (error) {
        if (!effectBoundaryEntered) {
          state.operations.delete(operationId);
          await this.#persist(state);
          throw error;
        }
        entry.receipt = unknown;
        entry.phase = "indeterminate";
        await this.#persist(state);
        return unknown;
      }
    });
  }

  async reconcileOperation(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return this.#locks.run(profileId, async () => {
      const state = await this.#profileForIdentity(input);
      const operationId = stableId(input.operationId, "operationId");
      const semanticDigest = digest(input.semanticDigest, "semanticDigest");
      const retired = state.retiredOperations.get(operationId);
      if (retired) {
        if (retired.semanticDigest !== semanticDigest) {
          throw new TypeError("operation reconciliation changed immutable semantics");
        }
        return retired.receipt;
      }
      const prior = state.operations.get(operationId);
      if (!prior) throw new TypeError("operation has not crossed the browser effect boundary");
      if (prior.semanticDigest !== semanticDigest) {
        throw new TypeError("operation reconciliation changed immutable semantics");
      }
      if (prior.receipt.terminalObserved === true) return prior.receipt;
      const observed = requireRecord(
        await callDriver(
          this.#driver,
          this.#clock,
          "reconcile",
          prior.semantics,
          recoveryDeadline(this.#clock, this.#defaultDriverTimeoutMs, input.deadlineMs),
        ),
        "driver reconciliation observation",
      );
      const receipt = effectReceipt(state.profileId, operationId, semanticDigest, observed);
      prior.receipt = receipt;
      prior.phase = receipt.terminalObserved ? "terminal" : "indeterminate";
      await this.#persist(state);
      return receipt;
    });
  }

  async acknowledgeTerminalOperation(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return this.#locks.run(profileId, async () => {
      const state = await this.#profileForIdentity(input);
      const operationId = stableId(input.operationId, "operationId");
      const semanticDigest = digest(input.semanticDigest, "semanticDigest");
      const entry = state.operations.get(operationId);
      if (!entry || entry.receipt.terminalObserved !== true) {
        throw new TypeError("operation is not terminal and cannot be compacted");
      }
      if (entry.semanticDigest !== semanticDigest) {
        throw new TypeError("operation acknowledgement changed immutable semantics");
      }
      if (state.retiredOperations.size >= MAX_RETIRED_OPERATIONS) {
        throw new TypeError("retired operation capacity is exhausted");
      }
      state.operations.delete(operationId);
      state.retiredOperations.set(operationId, {
        semanticDigest: entry.semanticDigest,
        semantics: entry.semantics,
        receipt: entry.receipt,
      });
      await this.#persist(state);
      return entry.receipt;
    });
  }

  async closeProfile(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return this.#locks.run(profileId, async () => {
      const state = await this.#profileForIdentity(input);
      if ([...state.operations.values()].some((entry) => entry.receipt.terminalObserved !== true)) {
        throw new TypeError("profile has indeterminate browser effects requiring reconciliation");
      }
      state.lifecycle = "closing";
      await this.#persist(state);
      const observed = requireRecord(
        await callDriver(
          this.#driver,
          this.#clock,
          "stop",
          { profileId: state.profileId, processId: state.processId, generation: state.generation },
          recoveryDeadline(this.#clock, this.#defaultDriverTimeoutMs, input.deadlineMs),
        ),
        "driver stop observation",
      );
      if (observed.stopped !== true) throw new TypeError("driver did not observe profile stop");
      this.#profiles.delete(state.profileId);
      await this.#store.deleteProfile(state.profileId);
      return freezeResult({
        kind: "BrowserProfileClosedV1",
        profileId: state.profileId,
        processId: state.processId,
        generation: state.generation,
        terminalObserved: true,
      });
    });
  }

  async #activeProfile(input) {
    const state = await this.#profileForIdentity(input);
    if (state.lifecycle !== "open") throw new TypeError(`profile is not active: ${state.lifecycle}`);
    if (this.#clock() >= state.expiresAtMs) throw new TypeError("profile grant has expired");
    return state;
  }

  async #profileForIdentity(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    let state = this.#profiles.get(profileId);
    if (!state) {
      const persisted = await this.#store.loadProfile(profileId);
      if (!persisted) throw new TypeError("profile is not open and has no durable recovery state");
      state = decodeState(persisted);
      this.#profiles.set(profileId, state);
    }
    if (input.principalId !== state.principalId) throw new TypeError("principal does not own the profile");
    if (input.generation !== state.generation) throw new TypeError("profile generation mismatch");
    return state;
  }

  #sessionReceipt(state, recovered) {
    return freezeResult({
      kind: "BrowserSessionV1",
      profileId: state.profileId,
      principalId: state.principalId,
      processId: state.processId,
      generation: state.generation,
      manifestDigest: state.manifestDigest,
      grantDigest: state.grantDigest,
      expiresAtMs: state.expiresAtMs,
      effectGrantCount: state.effectGrants.size,
      lifecycle: state.lifecycle,
      recovered,
    });
  }

  async #persist(state) {
    await this.#store.saveProfile(encodeState(state));
  }
}

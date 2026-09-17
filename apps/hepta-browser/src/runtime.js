import { createHash } from "node:crypto";

import {
  normalizeTypedAction,
  typedActionDestinationOrigin,
  typedActionDigest,
} from "./actions.js";

const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);
const MAX_ORIGINS = 128;
const MAX_EFFECT_GRANTS = 1024;
const MAX_OUTSTANDING_OPERATIONS = 1024;
const MAX_RETAINED_TERMINAL_OPERATIONS = 256;
const MAX_DRIVER_CALL_MS = 30_000;

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

function deadline(value, now, name = "deadlineMs", { allowExpired = false } = {}) {
  const deadlineMs = positiveInteger(value, name);
  if (!allowExpired && deadlineMs <= now) {
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

function parseVerifiedUse(value, now, { allowExpired = false } = {}) {
  const witness = requireRecord(value, "verifiedUse");
  return Object.freeze({
    witnessDigest: digest(witness.witnessDigest, "verifiedUse.witnessDigest"),
    grantDigest: digest(witness.grantDigest, "verifiedUse.grantDigest"),
    finalPayloadDigest: digest(
      witness.finalPayloadDigest,
      "verifiedUse.finalPayloadDigest",
    ),
    authorityEpoch: positiveInteger(
      witness.authorityEpoch,
      "verifiedUse.authorityEpoch",
    ),
    expiresAtMs: deadline(witness.expiresAtMs, now, "verifiedUse.expiresAtMs", { allowExpired }),
  });
}

function parseIsolation(value) {
  const isolation = requireRecord(value, "driver isolation observation");
  for (const field of [
    "processIsolationEnforced",
    "profileIsolationEnforced",
    "credentialIsolationEnforced",
    "networkPolicyEnforced",
  ]) {
    if (isolation[field] !== true) {
      throw new TypeError(`driver did not enforce ${field}`);
    }
  }
  return Object.freeze({
    processIsolationEnforced: true,
    profileIsolationEnforced: true,
    credentialIsolationEnforced: true,
    networkPolicyEnforced: true,
    sandboxDigest: digest(isolation.sandboxDigest, "isolation.sandboxDigest"),
    networkPolicyDigest: digest(
      isolation.networkPolicyDigest,
      "isolation.networkPolicyDigest",
    ),
  });
}

function driverDeadline(now, hardDeadline) {
  return Math.min(hardDeadline, now + MAX_DRIVER_CALL_MS);
}

async function callWithDeadline({ clock, deadlineMs, label, call }) {
  const now = clock();
  if (deadlineMs <= now) {
    throw new TypeError(`${label} deadline has expired`);
  }
  const controller = new AbortController();
  const remaining = Math.max(1, deadlineMs - now);
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      controller.abort(new Error(`${label} timed out`));
      const error = new Error(`${label} timed out`);
      error.code = "BROWSER_DRIVER_TIMEOUT";
      reject(error);
    }, remaining);
  });
  try {
    return await Promise.race([call(controller.signal), timeout]);
  } finally {
    clearTimeout(timer);
  }
}

export class BrowserProfileHost {
  #driver;
  #authority;
  #journal;
  #clock;
  #profiles = new Map();
  #locks = new Map();

  constructor({ driver, authority, journal, clock = () => Date.now() }) {
    requireRecord(driver, "driver");
    for (const method of ["start", "observe", "act", "reconcile", "stop"]) {
      if (typeof driver[method] !== "function") {
        throw new TypeError(`driver.${method} must be a function`);
      }
    }
    if (driver.supportsAbort !== true) {
      throw new TypeError("driver must declare supportsAbort=true");
    }
    requireRecord(authority, "authority");
    if (typeof authority.verifyFinalUse !== "function") {
      throw new TypeError("authority.verifyFinalUse must be a function");
    }
    requireRecord(journal, "journal");
    if (
      journal.durable !== true ||
      typeof journal.recordIntent !== "function" ||
      typeof journal.recordObservation !== "function" ||
      typeof journal.loadOutstandingOperations !== "function" ||
      typeof journal.findOperation !== "function"
    ) {
      throw new TypeError("journal must be a durable browser operation journal");
    }
    if (typeof clock !== "function") {
      throw new TypeError("clock must be a function");
    }
    this.#driver = driver;
    this.#authority = authority;
    this.#journal = journal;
    this.#clock = clock;
  }

  async openProfile(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return this.#withProfileLock(profileId, async () => {
      const principalId = stableId(input.principalId, "principalId");
      const manifestDigest = digest(input.manifestDigest, "manifestDigest");
      const grantDigest = digest(input.grantDigest, "grantDigest");
      const generation = positiveInteger(input.generation, "generation");
      const now = this.#clock();
      const expiresAtMs = deadline(input.expiresAtMs, now, "expiresAtMs");
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
        await callWithDeadline({
          clock: this.#clock,
          deadlineMs: driverDeadline(this.#clock(), expiresAtMs),
          label: "browser profile start",
          call: (signal) =>
            this.#driver.start(
              {
                profileId,
                principalId,
                manifestDigest,
                grantDigest,
                generation,
                allowedOrigins: [...allowedOrigins],
                requireIsolation: true,
              },
              { signal },
            ),
        }),
        "driver start observation",
      );
      if (observed.started !== true) {
        throw new TypeError("driver did not observe profile start");
      }
      const processId = stableId(observed.processId, "processId");
      const isolation = parseIsolation(observed.isolation);
      let outstanding;
      try {
        outstanding = await this.#journal.loadOutstandingOperations({
          profileId,
          generation,
        });
        if (outstanding.length > MAX_OUTSTANDING_OPERATIONS) {
          throw new TypeError("durable browser operation capacity is exhausted");
        }
      } catch (error) {
        try {
          await callWithDeadline({
            clock: this.#clock,
            deadlineMs: driverDeadline(this.#clock(), expiresAtMs),
            label: "browser profile rollback stop",
            call: (signal) =>
              this.#driver.stop(
                { profileId, processId, generation, reason: "journal_open_failed" },
                { signal },
              ),
          });
        } catch {
          // Startup remains failed closed even when cleanup itself is uncertain.
        }
        throw error;
      }
      const state = {
        profileId,
        principalId,
        manifestDigest,
        grantDigest,
        generation,
        expiresAtMs,
        processId,
        isolation,
        pageGeneration: 0,
        documentDigest: null,
        currentOrigin: null,
        allowedOrigins,
        effectGrants,
        operations: new Map(outstanding.map((entry) => [entry.operationId, entry])),
        terminalOrder: [],
        quarantined: false,
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
        isolation,
        recoveredOutstandingOperations: outstanding.length,
      });
    });
  }

  async observePage(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return this.#withProfileLock(profileId, async () => {
      const state = this.#profile(input);
      const observationBudget = positiveInteger(input.observationBudget, "observationBudget");
      if (observationBudget > 1_000_000) {
        throw new TypeError("observationBudget exceeds profile limit");
      }
      const observed = requireRecord(
        await callWithDeadline({
          clock: this.#clock,
          deadlineMs: driverDeadline(this.#clock(), state.expiresAtMs),
          label: "browser page observation",
          call: (signal) =>
            this.#driver.observe(
              {
                profileId: state.profileId,
                processId: state.processId,
                generation: state.generation,
                observationBudget,
              },
              { signal },
            ),
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
      state.currentOrigin = origin;
      const originAllowed = state.allowedOrigins.has(origin);
      if (!originAllowed) {
        state.quarantined = true;
        await this.#containProfile(state, "origin_escape");
      }
      return freezeResult({
        kind: "PageObservationV1",
        profileId: state.profileId,
        processId: state.processId,
        profileGeneration: state.generation,
        pageGeneration,
        documentDigest,
        origin,
        originAllowed,
        quarantined: state.quarantined,
        terminalObserved: true,
      });
    });
  }

  async navigateOrAct(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return this.#withProfileLock(profileId, async () => {
      const state = this.#profile(input);
      const operationId = stableId(input.operationId, "operationId");
      const prior = await this.#lookupOperation(state, operationId);
      if (prior) {
        this.#validateReplay(input, state, prior);
        return prior.receipt;
      }
      if (this.#outstandingCount(state) >= MAX_OUTSTANDING_OPERATIONS) {
        throw new TypeError("profile operation capacity is exhausted");
      }

      const admitted = await this.#admitNewOperation(input, state, operationId);
      const { semantics, semanticDigest, typedAction } = admitted;
      const receipt = this.#indeterminateReceipt(
        state.profileId,
        operationId,
        semanticDigest,
      );
      const durable = {
        profileId: state.profileId,
        generation: state.generation,
        operationId,
        semanticDigest,
        semantics,
        typedAction,
        receipt,
        createdAtMs: this.#clock(),
        updatedAtMs: this.#clock(),
      };

      // The durable intent and in-memory reservation are published before the
      // effect boundary. Once this succeeds, this operation identity is never
      // eligible for a fresh dispatch, even if the driver throws or the host
      // crashes after the remote effect may have happened.
      await this.#journal.recordIntent(durable);
      state.operations.set(operationId, durable);

      let observed;
      try {
        observed = requireRecord(
          await callWithDeadline({
            clock: this.#clock,
            deadlineMs: driverDeadline(this.#clock(), semantics.deadlineMs),
            label: "browser effect",
            call: (signal) =>
              this.#driver.act({ ...semantics, typedAction }, { signal }),
          }),
          "driver effect observation",
        );
      } catch {
        await this.#journal.recordObservation({
          profileId: state.profileId,
          generation: state.generation,
          operationId,
          receipt,
        });
        return receipt;
      }

      const observedReceipt = this.#effectReceipt(
        state.profileId,
        operationId,
        semanticDigest,
        observed,
      );
      await this.#journal.recordObservation({
        profileId: state.profileId,
        generation: state.generation,
        operationId,
        receipt: observedReceipt,
      });
      durable.receipt = observedReceipt;
      durable.updatedAtMs = this.#clock();
      this.#trackTerminal(state, durable);
      return observedReceipt;
    });
  }

  async reconcileOperation(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return this.#withProfileLock(profileId, async () => {
      const state = this.#profile(input, { allowExpired: true, allowQuarantined: true });
      const operationId = stableId(input.operationId, "operationId");
      const prior = await this.#lookupOperation(state, operationId);
      if (!prior) {
        throw new TypeError("operation has not crossed the browser effect boundary");
      }
      this.#validateRecoveryIdentity(input, state, prior);
      if (prior.receipt.terminalObserved === true) {
        return prior.receipt;
      }

      const reconcileDeadlineMs = input.reconcileDeadlineMs === undefined
        ? this.#clock() + MAX_DRIVER_CALL_MS
        : deadline(input.reconcileDeadlineMs, this.#clock(), "reconcileDeadlineMs");
      let observed;
      try {
        observed = requireRecord(
          await callWithDeadline({
            clock: this.#clock,
            deadlineMs: driverDeadline(this.#clock(), reconcileDeadlineMs),
            label: "browser reconciliation",
            call: (signal) =>
              this.#driver.reconcile(
                { ...prior.semantics, typedAction: prior.typedAction },
                { signal },
              ),
          }),
          "driver reconciliation observation",
        );
      } catch {
        return prior.receipt;
      }
      const receipt = this.#effectReceipt(
        state.profileId,
        operationId,
        prior.semanticDigest,
        observed,
      );
      if (receipt.terminalObserved === true) {
        await this.#journal.recordObservation({
          profileId: state.profileId,
          generation: state.generation,
          operationId,
          receipt,
        });
        prior.receipt = receipt;
        prior.updatedAtMs = this.#clock();
        this.#trackTerminal(state, prior);
      }
      return receipt;
    });
  }

  async closeProfile(input) {
    requireRecord(input, "input");
    const profileId = stableId(input.profileId, "profileId");
    return this.#withProfileLock(profileId, async () => {
      const state = this.#profile(input, { allowExpired: true, allowQuarantined: true });
      if (this.#outstandingCount(state) > 0) {
        throw new TypeError("profile has indeterminate browser effects requiring reconciliation");
      }
      const closeDeadlineMs = input.closeDeadlineMs === undefined
        ? this.#clock() + MAX_DRIVER_CALL_MS
        : deadline(input.closeDeadlineMs, this.#clock(), "closeDeadlineMs");
      const observed = requireRecord(
        await callWithDeadline({
          clock: this.#clock,
          deadlineMs: driverDeadline(this.#clock(), closeDeadlineMs),
          label: "browser profile stop",
          call: (signal) =>
            this.#driver.stop(
              {
                profileId: state.profileId,
                processId: state.processId,
                generation: state.generation,
              },
              { signal },
            ),
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
    });
  }

  async #admitNewOperation(input, state, operationId) {
    const pageGeneration = positiveInteger(input.pageGeneration, "pageGeneration");
    if (pageGeneration !== state.pageGeneration || state.documentDigest === null) {
      throw new TypeError("stale page generation");
    }
    const typedAction = normalizeTypedAction(input.typedAction);
    const action = stableId(input.action, "action");
    if (typedAction.kind !== action) {
      throw new TypeError("typed action kind does not match action");
    }
    const destinationOrigin = canonicalOrigin(input.destinationOrigin);
    const typedDestination = typedActionDestinationOrigin(typedAction, state.currentOrigin);
    if (destinationOrigin !== typedDestination) {
      throw new TypeError("destination origin does not match the typed action");
    }
    if (!state.allowedOrigins.has(destinationOrigin)) {
      throw new TypeError("destination origin is outside the profile grant");
    }
    const finalPayloadDigest = digest(input.finalPayloadDigest, "finalPayloadDigest");
    const actualPayloadDigest = typedActionDigest(typedAction);
    if (finalPayloadDigest !== actualPayloadDigest) {
      throw new TypeError("final payload digest does not bind the typed action");
    }
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
    const verifiedUse = parseVerifiedUse(input.verifiedUse, this.#clock());
    if (
      verifiedUse.grantDigest !== effectGrantDigest ||
      verifiedUse.finalPayloadDigest !== finalPayloadDigest ||
      verifiedUse.authorityEpoch !== authorityEpoch
    ) {
      throw new TypeError("verified use witness does not bind the final browser operation");
    }

    const authorityRequest = Object.freeze({
      profileId: state.profileId,
      principalId: state.principalId,
      profileGeneration: state.generation,
      pageGeneration,
      documentDigest: state.documentDigest,
      operationId,
      action,
      destinationOrigin,
      finalPayloadDigest,
      effectGrantDigest,
      authorityEpoch,
      deadlineMs,
      verifiedUseWitnessDigest: verifiedUse.witnessDigest,
    });
    const authorityObservation = requireRecord(
      await callWithDeadline({
        clock: this.#clock,
        deadlineMs: driverDeadline(this.#clock(), deadlineMs),
        label: "final browser authority verification",
        call: (signal) =>
          this.#authority.verifyFinalUse(
            {
              request: authorityRequest,
              grant,
              verifiedUse,
            },
            { signal },
          ),
      }),
      "authority verification observation",
    );
    if (authorityObservation.authorized !== true) {
      throw new TypeError("final browser authority verification was denied");
    }
    const authorityReceiptDigest = digest(
      authorityObservation.authorityReceiptDigest,
      "authorityReceiptDigest",
    );
    const revocationRevision = positiveInteger(
      authorityObservation.revocationRevision,
      "revocationRevision",
    );
    if (
      authorityObservation.grantDigest !== effectGrantDigest ||
      authorityObservation.finalPayloadDigest !== finalPayloadDigest ||
      authorityObservation.authorityEpoch !== authorityEpoch ||
      authorityObservation.verifiedUseWitnessDigest !== verifiedUse.witnessDigest
    ) {
      throw new TypeError("authority observation does not bind the final browser operation");
    }
    if (this.#clock() >= deadlineMs) {
      throw new TypeError("deadlineMs has expired after final authority verification");
    }

    const semantics = Object.freeze({
      ...authorityRequest,
      processId: state.processId,
      profileGrantDigest: state.grantDigest,
      authorityReceiptDigest,
      revocationRevision,
      sandboxDigest: state.isolation.sandboxDigest,
      networkPolicyDigest: state.isolation.networkPolicyDigest,
    });
    return {
      semantics,
      typedAction,
      semanticDigest: canonicalDigest(semantics),
    };
  }

  #validateReplay(input, state, prior) {
    const typedAction = normalizeTypedAction(input.typedAction);
    const finalPayloadDigest = digest(input.finalPayloadDigest, "finalPayloadDigest");
    const verifiedUse = parseVerifiedUse(input.verifiedUse, this.#clock(), { allowExpired: true });
    if (
      input.principalId !== state.principalId ||
      input.generation !== state.generation ||
      stableId(input.operationId, "operationId") !== prior.operationId ||
      positiveInteger(input.pageGeneration, "pageGeneration") !== prior.semantics.pageGeneration ||
      stableId(input.action, "action") !== prior.semantics.action ||
      canonicalOrigin(input.destinationOrigin) !== prior.semantics.destinationOrigin ||
      finalPayloadDigest !== prior.semantics.finalPayloadDigest ||
      typedActionDigest(typedAction) !== prior.semantics.finalPayloadDigest ||
      digest(input.effectGrantDigest, "effectGrantDigest") !== prior.semantics.effectGrantDigest ||
      positiveInteger(input.authorityEpoch, "authorityEpoch") !== prior.semantics.authorityEpoch ||
      verifiedUse.witnessDigest !== prior.semantics.verifiedUseWitnessDigest ||
      verifiedUse.grantDigest !== prior.semantics.effectGrantDigest ||
      verifiedUse.finalPayloadDigest !== prior.semantics.finalPayloadDigest ||
      verifiedUse.authorityEpoch !== prior.semantics.authorityEpoch ||
      deadline(input.deadlineMs, this.#clock(), "deadlineMs", { allowExpired: true }) !==
        prior.semantics.deadlineMs
    ) {
      throw new TypeError("operation identity was reused with changed semantics");
    }
  }

  #validateRecoveryIdentity(input, state, prior) {
    if (input.principalId !== state.principalId || input.generation !== state.generation) {
      throw new TypeError("operation reconciliation changed immutable identity");
    }
    if (input.typedAction !== undefined) {
      const action = normalizeTypedAction(input.typedAction);
      if (typedActionDigest(action) !== prior.semantics.finalPayloadDigest) {
        throw new TypeError("operation reconciliation changed immutable semantics");
      }
    }
  }

  #indeterminateReceipt(profileId, operationId, semanticDigest) {
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

  #effectReceipt(profileId, operationId, semanticDigest, observed) {
    if (observed.terminalObserved !== true) {
      return this.#indeterminateReceipt(profileId, operationId, semanticDigest);
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

  async #lookupOperation(state, operationId) {
    const cached = state.operations.get(operationId);
    if (cached) {
      return cached;
    }
    const durable = await this.#journal.findOperation({
      profileId: state.profileId,
      generation: state.generation,
      operationId,
    });
    if (durable) {
      state.operations.set(operationId, durable);
      if (durable.receipt?.terminalObserved === true) {
        this.#trackTerminal(state, durable);
      }
    }
    return durable;
  }

  #trackTerminal(state, operation) {
    if (operation.receipt?.terminalObserved !== true) {
      return;
    }
    state.terminalOrder = state.terminalOrder.filter((id) => id !== operation.operationId);
    state.terminalOrder.push(operation.operationId);
    while (state.terminalOrder.length > MAX_RETAINED_TERMINAL_OPERATIONS) {
      const evicted = state.terminalOrder.shift();
      const entry = state.operations.get(evicted);
      if (entry?.receipt?.terminalObserved === true) {
        state.operations.delete(evicted);
      }
    }
  }

  #outstandingCount(state) {
    let count = 0;
    for (const entry of state.operations.values()) {
      if (entry.receipt?.terminalObserved !== true) {
        count += 1;
      }
    }
    return count;
  }

  #profile(input, { allowExpired = false, allowQuarantined = false } = {}) {
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
    if (!allowExpired && this.#clock() >= state.expiresAtMs) {
      throw new TypeError("profile grant has expired");
    }
    if (!allowQuarantined && state.quarantined) {
      throw new TypeError("profile is quarantined");
    }
    return state;
  }

  async #containProfile(state, reason) {
    const payload = {
      profileId: state.profileId,
      processId: state.processId,
      generation: state.generation,
      reason,
    };
    try {
      if (typeof this.#driver.contain === "function") {
        await callWithDeadline({
          clock: this.#clock,
          deadlineMs: this.#clock() + MAX_DRIVER_CALL_MS,
          label: "browser containment",
          call: (signal) => this.#driver.contain(payload, { signal }),
        });
      } else {
        await callWithDeadline({
          clock: this.#clock,
          deadlineMs: this.#clock() + MAX_DRIVER_CALL_MS,
          label: "browser containment stop",
          call: (signal) => this.#driver.stop(payload, { signal }),
        });
      }
    } catch {
      // The in-memory profile remains quarantined even when process cleanup is
      // uncertain. New effects stay denied; operators must reconcile/cleanup.
    }
  }

  async #withProfileLock(profileId, task) {
    const previous = this.#locks.get(profileId) ?? Promise.resolve();
    let release;
    const gate = new Promise((resolve) => {
      release = resolve;
    });
    const tail = previous.catch(() => {}).then(() => gate);
    this.#locks.set(profileId, tail);
    await previous.catch(() => {});
    try {
      return await task();
    } finally {
      release();
      if (this.#locks.get(profileId) === tail) {
        this.#locks.delete(profileId);
      }
    }
  }
}

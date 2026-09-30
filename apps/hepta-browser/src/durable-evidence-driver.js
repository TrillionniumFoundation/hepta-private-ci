import { canonicalDigest } from "./runtime-contract.js";

function requireCapability(value, name) {
  if (value === null || typeof value !== "object") {
    throw new TypeError(`${name} must be an object capability`);
  }
  return value;
}

function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

function requestIdentity(input) {
  const semantics = { ...input };
  delete semantics.verifiedUseTokenWitnessDigest;
  return Object.freeze({
    profileId: input.profileId,
    generation: input.profileGeneration ?? input.generation,
    operationId: input.operationId,
    requestDigest: canonicalDigest(semantics),
    semanticDigest: canonicalDigest(input),
  });
}

function deferSettlement(settlement, handler) {
  // Attach immediately so a rejected inner settlement is always observed, but
  // defer durable terminal/egress work until after dispatch() has returned the
  // admission boundary to its caller. A resolved Promise otherwise schedules
  // its .then() before the caller's await continuation and silently widens the
  // live final-use critical section.
  const captured = Promise.resolve(settlement).then(
    (value) => ({ ok: true, value }),
    (error) => ({ ok: false, error }),
  );
  return new Promise((resolve, reject) => {
    setImmediate(() => {
      captured
        .then((outcome) => {
          if (!outcome.ok) throw outcome.error;
          return handler(outcome.value);
        })
        .then(resolve, reject);
    });
  });
}

/**
 * Binds worker admission and operation-scoped network receipts to the same
 * durable operation identity owned by BrowserProfileHost.
 *
 * BrowserProfileHost records the immutable dispatch before calling this
 * driver. `dispatch()` does not return to the final-use authority boundary
 * until the worker admission receipt is durably recorded. Terminal egress
 * receipts are persisted on direct settlement, deferred settlement, and live
 * reconciliation. Missing evidence never becomes success.
 */
export class DurableEvidenceBrowserDriver {
  supportsAbort = true;
  maxActiveProfiles;
  maxOutstandingOperations;

  #driver;
  #journal;

  constructor({ driver, journal }) {
    requireCapability(driver, "durable evidence driver");
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
        throw new TypeError(`durable evidence driver.${method} is required`);
      }
    }
    if (driver.supportsAbort !== true) {
      throw new TypeError("durable evidence driver must support abort");
    }
    requireCapability(journal, "durable evidence journal");
    for (const method of ["recordAdmission", "recordEgress"]) {
      if (typeof journal[method] !== "function") {
        throw new TypeError(`durable evidence journal.${method} is required`);
      }
    }
    this.#driver = driver;
    this.#journal = journal;
    this.maxActiveProfiles = driver.maxActiveProfiles;
    this.maxOutstandingOperations = driver.maxOutstandingOperations;
  }

  start(input, options = {}) {
    return this.#driver.start(input, options);
  }

  observe(input, options = {}) {
    return this.#driver.observe(input, options);
  }

  async dispatch(input, options = {}) {
    const identity = requestIdentity(input);
    const observed = requireRecord(
      await this.#driver.dispatch(input, options),
      "durable evidence dispatch observation",
    );
    const admission = requireRecord(
      observed.admission,
      "durable evidence worker admission",
    );
    await this.#journal.recordAdmission({ ...identity, admission });
    await this.#persistEgress(identity, observed);

    if (observed.settlement && typeof observed.settlement.then === "function") {
      const settlement = deferSettlement(observed.settlement, async (value) => {
        const terminal = requireRecord(
          value,
          "durable evidence terminal settlement",
        );
        await this.#persistEgress(identity, terminal);
        return terminal;
      });
      return Object.freeze({ ...observed, settlement });
    }
    return observed;
  }

  async reconcile(input, options = {}) {
    const identity = requestIdentity(input);
    const observed = requireRecord(
      await this.#driver.reconcile(input, options),
      "durable evidence reconciliation observation",
    );
    await this.#persistEgress(identity, observed);
    return observed;
  }

  reconcilePersisted(input, options = {}) {
    return this.#driver.reconcilePersisted(input, options);
  }

  contain(input) {
    return this.#driver.contain(input);
  }

  stop(input, options = {}) {
    return this.#driver.stop(input, options);
  }

  async #persistEgress(identity, observed) {
    if (observed.egressReceipt === undefined) return;
    const receipt = requireRecord(
      observed.egressReceipt,
      "durable evidence egress receipt",
    );
    await this.#journal.recordEgress({ ...identity, receipt });
  }
}

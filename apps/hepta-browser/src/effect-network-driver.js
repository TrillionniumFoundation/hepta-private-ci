import {
  lstat,
  mkdtemp,
  realpath,
  rm,
  readdir,
  rename,
} from "node:fs/promises";
import { isAbsolute, join, resolve } from "node:path";

import { EffectScopedEgressBroker } from "./effect-egress-gate.js";

const DEFAULT_MAX_REQUEST_BYTES = 1 * 1024 * 1024;
const DEFAULT_MAX_RESPONSE_BYTES = 32 * 1024 * 1024;
const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;

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

function positiveInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

/**
 * Inserts a one-operation egress gate in front of the existing profile policy
 * broker without changing the worker-visible socket path.
 *
 * The underlying driver creates `.hepta-egress.sock`. After worker startup and
 * before any admitted navigation, this wrapper atomically renames that socket
 * into a fresh host-private directory OUTSIDE the writable profile bind and
 * installs the effect gate at the original path. The worker must never see the
 * upstream endpoint, otherwise it could bypass operation-scoped admission.
 * The existing DNS/IP/SNI broker remains the upstream policy authority.
 */
export class EffectScopedNetworkDriver {
  supportsAbort = true;
  maxActiveProfiles;
  maxOutstandingOperations;

  #driver;
  #profileRoot;
  #maxRequestBytes;
  #maxResponseBytes;
  #sessions = new Map();

  constructor({
    driver,
    profileRoot,
    maxRequestBytes = DEFAULT_MAX_REQUEST_BYTES,
    maxResponseBytes = DEFAULT_MAX_RESPONSE_BYTES,
  }) {
    requireRecord(driver, "effect network driver");
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
        throw new TypeError(`effect network driver.${method} is required`);
      }
    }
    if (driver.supportsAbort !== true) {
      throw new TypeError("effect network driver must support abort");
    }
    if (typeof profileRoot !== "string" || !isAbsolute(profileRoot)) {
      throw new TypeError("effect network profileRoot must be absolute");
    }
    this.#driver = driver;
    this.#profileRoot = profileRoot;
    this.#maxRequestBytes = positiveInteger(
      maxRequestBytes,
      "maxRequestBytes",
    );
    this.#maxResponseBytes = positiveInteger(
      maxResponseBytes,
      "maxResponseBytes",
    );
    this.maxActiveProfiles = driver.maxActiveProfiles;
    this.maxOutstandingOperations = driver.maxOutstandingOperations;
  }

  async start(input, options = {}) {
    requireRecord(input, "effect network start input");
    const profileId = stableId(input.profileId, "profileId");
    const generation = positiveInteger(input.generation, "generation");
    const observed = requireRecord(
      await this.#driver.start(input, options),
      "effect network start observation",
    );
    let gate = null;
    let policyDir = null;
    try {
      const profileDir = await this.#findProfileDirectory(profileId, generation);
      const publicSocketPath = join(profileDir, ".hepta-egress.sock");
      // Only profileDir is mounted into Servo. This sibling is host-private;
      // keeping the policy socket inside profileDir defeats the effect gate.
      policyDir = await mkdtemp(join(this.#profileRoot, ".egress-"));
      const policySocketPath = join(policyDir, "policy.sock");
      const metadata = await lstat(publicSocketPath);
      if (!metadata.isSocket() || metadata.isSymbolicLink()) {
        throw new TypeError(
          "Browser profile egress endpoint is not a non-symlink Unix socket",
        );
      }
      await rename(publicSocketPath, policySocketPath);
      gate = new EffectScopedEgressBroker({
        socketPath: publicSocketPath,
        upstreamSocketPath: policySocketPath,
        grantDigest: input.grantDigest,
        allowedOrigins: input.allowedOrigins,
        maxRequestBytes: this.#maxRequestBytes,
        maxResponseBytes: this.#maxResponseBytes,
      });
      await gate.start();
      this.#sessions.set(profileId, {
        profileId,
        generation,
        processId: observed.processId,
        profileDir,
        publicSocketPath,
        policySocketPath,
        policyDir,
        gate,
        closed: false,
      });
      return observed;
    } catch (error) {
      await gate?.close({ status: "composition_failed" }).catch(() => {});
      await this.#driver
        .contain({
          profileId,
          generation,
          processId: observed.processId,
          reason: "effect_network_composition_failed",
        })
        .catch(() => {});
      if (policyDir !== null) {
        await rm(policyDir, { recursive: true, force: true });
      }
      throw error;
    }
  }

  async observe(input, options = {}) {
    this.#session(input);
    return this.#driver.observe(input, options);
  }

  async dispatch(input, options = {}) {
    const session = this.#session(input);
    session.gate.admitOperation({
      operationId: input.operationId,
      effectGrantDigest: input.effectGrantDigest,
      destinationOrigin: input.destinationOrigin,
      deadlineMs: input.deadlineMs,
    });
    try {
      const observed = requireRecord(
        await this.#driver.dispatch(input, options),
        "effect network dispatch observation",
      );
      if (observed.settlement && typeof observed.settlement.then === "function") {
        const settlement = observed.settlement.then((value) =>
          this.#settle(session, input.operationId, value),
        );
        return Object.freeze({ ...observed, settlement });
      }
      return this.#settle(session, input.operationId, observed);
    } catch (error) {
      if (error?.code === "BROWSER_WORKER_PRE_DISPATCH_REJECTED") {
        session.gate.completeOperation(input.operationId, {
          status: "worker_rejected_before_admission",
        });
      }
      throw error;
    }
  }

  async reconcile(input, options = {}) {
    const session = this.#session(input);
    const observed = requireRecord(
      await this.#driver.reconcile(input, options),
      "effect network reconciliation observation",
    );
    return this.#settle(session, input.operationId, observed);
  }

  async reconcilePersisted(input, options = {}) {
    return this.#driver.reconcilePersisted(input, options);
  }

  async contain(input) {
    const session = this.#session(input, {
      allowMissing: true,
      allowClosed: true,
    });
    if (session === null) return this.#driver.contain(input);
    let gateError = null;
    try {
      await this.#closeGate(session, "contained");
    } catch (error) {
      gateError = error;
    }
    // Gate cleanup errors must never prevent the underlying process kill.
    try {
      const observed = await this.#driver.contain(input);
      if (gateError !== null) throw gateError;
      return observed;
    } finally {
      await rm(session.policyDir, { recursive: true, force: true });
    }
  }

  async stop(input, options = {}) {
    const session = this.#session(input, {
      allowMissing: true,
      allowClosed: true,
    });
    if (session === null) return this.#driver.stop(input, options);
    let gateError = null;
    try {
      await this.#closeGate(session, "profile_stopped");
    } catch (error) {
      gateError = error;
    }
    try {
      const observed = await this.#driver.stop(input, options);
      // Retain a closed session if process stop fails: a later cleanup retry
      // must not lose the ownership record or admit a new worker implicitly.
      this.#sessions.delete(session.profileId);
      if (gateError !== null) throw gateError;
      return observed;
    } finally {
      await rm(session.policyDir, { recursive: true, force: true });
    }
  }

  #settle(session, operationId, observed) {
    const value = requireRecord(observed, "effect network terminal observation");
    if (value.terminalObserved !== true) return value;
    const receipt = session.gate.completeOperation(operationId, {
      status: value.status ?? "terminal_observed",
    });
    return Object.freeze({ ...value, egressReceipt: receipt });
  }

  async #closeGate(session, status) {
    if (session.closed) return;
    session.closed = true;
    await session.gate.close({ status });
  }

  #session(
    input,
    { allowMissing = false, allowClosed = false } = {},
  ) {
    requireRecord(input, "effect network request");
    const profileId = stableId(input.profileId, "profileId");
    const session = this.#sessions.get(profileId) ?? null;
    if (session === null) {
      if (allowMissing) return null;
      throw new TypeError("effect network profile is not started");
    }
    const generation = positiveInteger(
      input.generation ?? input.profileGeneration,
      "generation",
    );
    if (generation !== session.generation) {
      throw new TypeError("effect network profile generation mismatch");
    }
    if (input.processId !== undefined && input.processId !== session.processId) {
      throw new TypeError("effect network process identity mismatch");
    }
    if (session.closed && !allowClosed) {
      throw new TypeError("effect network profile is closed");
    }
    return session;
  }

  async #findProfileDirectory(profileId, generation) {
    if (await realpath(this.#profileRoot) !== resolve(this.#profileRoot)) {
      throw new TypeError("effect network profile root contains a symlink");
    }
    const prefix = `${profileId}.${generation}.`;
    const entries = await readdir(this.#profileRoot, { withFileTypes: true });
    const matches = entries.filter(
      (entry) => entry.isDirectory() && entry.name.startsWith(prefix),
    );
    if (matches.length !== 1) {
      throw new TypeError(
        "effect network composition requires one exact profile directory",
      );
    }
    const path = join(this.#profileRoot, matches[0].name);
    const metadata = await lstat(path);
    if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
      throw new TypeError(
        "effect network profile path is not a non-symlink directory",
      );
    }
    return path;
  }
}

import {
  lstat,
  readdir,
  rename,
  unlink,
} from "node:fs/promises";
import { isAbsolute, join } from "node:path";

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

async function removeSocket(path) {
  await unlink(path).catch((error) => {
    if (error?.code !== "ENOENT") throw error;
  });
}

/**
 * Inserts a one-operation egress gate in front of the existing profile policy
 * broker without changing the worker-visible socket path.
 *
 * The underlying driver creates `.hepta-egress.sock`. After worker startup and
 * before any admitted navigation, this wrapper atomically renames that socket
 * to `.hepta-egress-policy.sock` and installs the effect gate at the original
 * path. The existing DNS/IP/SNI broker remains the upstream policy authority.
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
    let session = null;
    try {
      const profileDir = await this.#findProfileDirectory(profileId, generation);
      const publicSocketPath = join(profileDir, ".hepta-egress.sock");
      const policySocketPath = join(
        profileDir,
        ".hepta-egress-policy.sock",
      );
      const metadata = await lstat(publicSocketPath);
      if (!metadata.isSocket() || metadata.isSymbolicLink()) {
        throw new TypeError(
          "Browser profile egress endpoint is not a non-symlink Unix socket",
        );
      }
      await removeSocket(policySocketPath);
      await rename(publicSocketPath, policySocketPath);
      const gate = new EffectScopedEgressBroker({
        socketPath: publicSocketPath,
        upstreamSocketPath: policySocketPath,
        grantDigest: input.grantDigest,
        allowedOrigins: input.allowedOrigins,
        maxRequestBytes: this.#maxRequestBytes,
        maxResponseBytes: this.#maxResponseBytes,
      });
      await gate.start();
      session = {
        profileId,
        generation,
        processId: observed.processId,
        profileDir,
        publicSocketPath,
        policySocketPath,
        gate,
        closed: false,
      };
      this.#sessions.set(profileId, session);
      return observed;
    } catch (error) {
      await session?.gate.close().catch(() => {});
      await this.#driver
        .contain({
          profileId,
          generation,
          processId: observed.processId,
          reason: "effect_network_composition_failed",
        })
        .catch(() => {});
      throw error;
    }
  }

  observe(input, options = {}) {
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

  reconcilePersisted(input, options = {}) {
    return this.#driver.reconcilePersisted(input, options);
  }

  async contain(input) {
    const session = this.#session(input, { allowMissing: true });
    if (session === null) return this.#driver.contain(input);
    await this.#closeGate(session, "contained");
    try {
      return await this.#driver.contain(input);
    } finally {
      await removeSocket(session.policySocketPath).catch(() => {});
    }
  }

  async stop(input, options = {}) {
    const session = this.#session(input, { allowMissing: true });
    if (session === null) return this.#driver.stop(input, options);
    await this.#closeGate(session, "profile_stopped");
    try {
      return await this.#driver.stop(input, options);
    } finally {
      this.#sessions.delete(session.profileId);
      await Promise.all([
        removeSocket(session.publicSocketPath).catch(() => {}),
        removeSocket(session.policySocketPath).catch(() => {}),
      ]);
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
    const activeReceipt = session.gate.receipts.at(-1);
    if (activeReceipt?.status !== status) {
      // close() emits a profile_closed receipt for any still-active operation.
      await session.gate.close();
    }
  }

  #session(input, { allowMissing = false } = {}) {
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
    if (session.closed) {
      throw new TypeError("effect network profile is closed");
    }
    return session;
  }

  async #findProfileDirectory(profileId, generation) {
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

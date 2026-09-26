import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

import {
  AgentdBrowserFrameDecoder,
  encodeAgentdBrowserFrame,
  buildAgentdBrowserFrame,
} from "./agentd-protocol.js";
import { canonicalDigest } from "./runtime-contract.js";

const MAX_QUEUED_AGENTD_FRAMES = 64;
const DEFAULT_CONTAINMENT_TIMEOUT_MS = 10_000;
const CONTAINMENT_POLL_MS = 10;

const SERVICE_METHODS = new Set([
  "open_profile",
  "admit_effect_grant",
  "observe_page",
  "navigate_or_act",
  "reconcile_operation",
  "reconcile_persisted_operation",
  "close_profile",
]);

function requireRecord(value, name) {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    Object.getPrototypeOf(value) !== Object.prototype
  ) {
    throw new TypeError(`${name} must be a plain object`);
  }
  return value;
}

function boundedError(error) {
  return String(error?.message ?? error ?? "browser service error").slice(0, 512);
}

function digest(value, name) {
  if (
    typeof value !== "string" ||
    !/^[0-9a-f]{64}$/.test(value) ||
    /^0+$/.test(value)
  ) {
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

function nonNegativeInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new TypeError(`${name} must be a non-negative safe integer`);
  }
  return value;
}

function stableId(value, name) {
  if (
    typeof value !== "string" ||
    !/^[A-Za-z0-9._:-]{1,128}$/.test(value)
  ) {
    throw new TypeError(`${name} must be a bounded stable identifier`);
  }
  return value;
}

function exactKeys(value, expected, name) {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (
    actual.length !== wanted.length ||
    actual.some((key, index) => key !== wanted[index])
  ) {
    throw new TypeError(`${name} contains missing or unknown fields`);
  }
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function processIdFromBrowserIdentity(value) {
  if (typeof value !== "string") return null;
  const match = /^servo\.pid\.(\d+)\.[0-9a-f-]{36}$/.exec(value);
  if (!match) return null;
  const pid = Number(match[1]);
  return Number.isSafeInteger(pid) && pid > 0 ? pid : null;
}

async function linuxProcessIdentity(pid) {
  try {
    const stat = await readFile(`/proc/${pid}/stat`, "utf8");
    const closing = stat.lastIndexOf(")");
    if (closing < 0) throw new Error("process stat has no command terminator");
    const fields = stat.slice(closing + 2).trim().split(/\s+/);
    // /proc/<pid>/stat field 22 is starttime. The slice begins at field 3.
    const startTime = fields[19];
    if (!/^\d+$/.test(startTime ?? "")) {
      throw new Error("process stat has no valid start time");
    }
    let children = [];
    try {
      const raw = await readFile(`/proc/${pid}/task/${pid}/children`, "utf8");
      children = raw
        .trim()
        .split(/\s+/)
        .filter(Boolean)
        .map(Number)
        .filter((value) => Number.isSafeInteger(value) && value > 0);
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
    return { pid, startTime, children };
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

async function captureLinuxProcessTree(rootPid) {
  if (process.platform !== "linux" || rootPid === null) return [];
  const identities = [];
  const pending = [rootPid];
  const seen = new Set();
  while (pending.length > 0) {
    const pid = pending.pop();
    if (seen.has(pid)) continue;
    seen.add(pid);
    const identity = await linuxProcessIdentity(pid);
    if (identity === null) continue;
    identities.push(
      Object.freeze({ pid: identity.pid, startTime: identity.startTime }),
    );
    pending.push(...identity.children);
  }
  return identities;
}

function mergeProcessIdentities(...groups) {
  const merged = new Map();
  for (const group of groups) {
    for (const identity of group) {
      merged.set(`${identity.pid}:${identity.startTime}`, identity);
    }
  }
  return [...merged.values()];
}

async function sameLinuxProcessAlive(identity) {
  const current = await linuxProcessIdentity(identity.pid);
  return current !== null && current.startTime === identity.startTime;
}

async function waitForLinuxProcessTreeExit(
  identities,
  timeoutMs = DEFAULT_CONTAINMENT_TIMEOUT_MS,
) {
  positiveInteger(timeoutMs, "containmentTimeoutMs");
  if (process.platform !== "linux" || identities.length === 0) return;
  const deadline = Date.now() + timeoutMs;
  while (true) {
    const alive = [];
    for (const identity of identities) {
      if (await sameLinuxProcessAlive(identity)) alive.push(identity.pid);
    }
    if (alive.length === 0) return;
    if (Date.now() >= deadline) {
      const error = new Error(
        `browser worker containment did not terminate process identities: ${alive.join(",")}`,
      );
      error.name = "BrowserContainmentError";
      error.code = "BROWSER_CONTAINMENT_UNPROVED";
      throw error;
    }
    await delay(CONTAINMENT_POLL_MS);
  }
}

function containmentDigest(identities) {
  return createHash("sha256")
    .update(JSON.stringify(identities))
    .digest("hex");
}

function validateBrowserEffectAdmission(admission, request) {
  const value = requireRecord(admission, "Browser effect admission");
  exactKeys(
    value,
    [
      "admittedAt",
      "durableOrRecoverable",
      "kind",
      "operationId",
      "pageRevision",
      "semanticDigest",
      "workerGeneration",
    ],
    "Browser effect admission",
  );
  if (value.kind !== "BrowserEffectAdmissionV1") {
    throw new TypeError("Browser effect admission kind is unsupported");
  }
  if (
    stableId(value.operationId, "admission.operationId") !==
    stableId(request.operationId, "request.operationId")
  ) {
    throw new TypeError("Browser effect admission operation identity drifted");
  }
  digest(value.semanticDigest, "admission.semanticDigest");
  if (
    positiveInteger(value.workerGeneration, "admission.workerGeneration") !==
    positiveInteger(
      request.profileGeneration ?? request.generation,
      "request.profileGeneration",
    )
  ) {
    throw new TypeError("Browser effect admission worker generation drifted");
  }
  if (
    nonNegativeInteger(value.pageRevision, "admission.pageRevision") !==
    nonNegativeInteger(request.pageGeneration, "request.pageGeneration")
  ) {
    throw new TypeError("Browser effect admission page revision drifted");
  }
  positiveInteger(value.admittedAt, "admission.admittedAt");
  if (value.durableOrRecoverable !== true) {
    throw new TypeError(
      "Browser effect admission did not prove durable or recoverable identity",
    );
  }
  return Object.freeze({ ...value });
}

/**
 * Production decorator for the profile-affine subprocess pool.
 *
 * The inner driver already returns only after the Servo worker's admission
 * boundary. This decorator turns that boundary into a closed
 * BrowserEffectAdmissionV1 and, on uncertain pre-boundary failure, requires the
 * exact Linux worker process tree to disappear before reporting containment.
 */
export class EffectAdmissionBrowserDriver {
  supportsAbort = true;
  maxActiveProfiles;
  maxOutstandingOperations;

  #driver;
  #clock;
  #containmentTimeoutMs;
  #sessions = new Map();
  #expiryTimers = new Map();

  constructor({
    driver,
    clock = () => Date.now(),
    containmentTimeoutMs = DEFAULT_CONTAINMENT_TIMEOUT_MS,
  }) {
    requireRecord(driver, "effect admission driver");
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
        throw new TypeError(`effect admission driver.${method} is required`);
      }
    }
    if (driver.supportsAbort !== true) {
      throw new TypeError("effect admission driver must support abort");
    }
    if (typeof clock !== "function") throw new TypeError("clock must be a function");
    positiveInteger(containmentTimeoutMs, "containmentTimeoutMs");
    this.#driver = driver;
    this.#clock = clock;
    this.#containmentTimeoutMs = containmentTimeoutMs;
    this.maxActiveProfiles = driver.maxActiveProfiles;
    this.maxOutstandingOperations = driver.maxOutstandingOperations;
  }

  async start(input, options = {}) {
    const observed = requireRecord(
      await this.#driver.start(input, options),
      "effect admission start observation",
    );
    const profileId = stableId(input.profileId, "profileId");
    const generation = positiveInteger(input.generation, "generation");
    const processId = stableId(observed.processId, "processId");
    this.#sessions.set(profileId, {
      generation,
      processId,
      pid: processIdFromBrowserIdentity(processId),
      contained: false,
      containmentProof: null,
    });
    this.#armExpiry(profileId, positiveInteger(input.expiresAtMs, "expiresAtMs"));
    return observed;
  }

  observe(input, options = {}) {
    this.#session(input);
    return this.#driver.observe(input, options);
  }

  async dispatch(input, options = {}) {
    requireRecord(input, "effect admission dispatch input");
    const session = this.#session(input);
    const tree = await captureLinuxProcessTree(session.pid);
    try {
      const observed = requireRecord(
        await this.#driver.dispatch(input, options),
        "effect admission dispatch observation",
      );
      const admission = Object.freeze({
        kind: "BrowserEffectAdmissionV1",
        operationId: stableId(input.operationId, "operationId"),
        semanticDigest: canonicalDigest(input),
        workerGeneration: positiveInteger(
          input.profileGeneration ?? input.generation,
          "profileGeneration",
        ),
        pageRevision: nonNegativeInteger(input.pageGeneration, "pageGeneration"),
        admittedAt: positiveInteger(this.#clock(), "admittedAt"),
        // BrowserProfileHost fsyncs the immutable dispatch identity before the
        // inner driver can reach this method. The underlying return is itself
        // gated by the worker reservation boundary.
        durableOrRecoverable: true,
      });
      return Object.freeze({ ...observed, admission });
    } catch (error) {
      if (error?.code === "BROWSER_WORKER_PRE_DISPATCH_REJECTED") throw error;
      const proof = await this.#containAndProve(input, tree);
      if (error && typeof error === "object") {
        error.workerContained = true;
        error.containmentDigest = proof.containmentDigest;
        error.containedProcessCount = proof.processCount;
      }
      throw error;
    }
  }

  reconcile(input, options = {}) {
    this.#session(input);
    return this.#driver.reconcile(input, options);
  }

  reconcilePersisted(input, options = {}) {
    return this.#driver.reconcilePersisted(input, options);
  }

  async contain(input) {
    const session = this.#session(input, {
      allowMissing: true,
      allowContained: true,
    });
    if (session === null) return { contained: true };
    if (session.contained && session.containmentProof !== null) {
      return Object.freeze({
        contained: true,
        ...session.containmentProof,
      });
    }
    const tree = await captureLinuxProcessTree(session.pid);
    const proof = await this.#containAndProve(input, tree);
    return Object.freeze({ contained: true, ...proof });
  }

  async stop(input, options = {}) {
    const profileId = stableId(input.profileId, "profileId");
    const session = this.#sessions.get(profileId) ?? null;
    const tree = await captureLinuxProcessTree(session?.pid ?? null);
    this.#clearExpiry(profileId);
    const observed = await this.#driver.stop(input, options);
    await waitForLinuxProcessTreeExit(tree, this.#containmentTimeoutMs);
    this.#sessions.delete(profileId);
    return observed;
  }

  #session(
    input,
    { allowMissing = false, allowContained = false } = {},
  ) {
    const profileId = stableId(input.profileId, "profileId");
    const session = this.#sessions.get(profileId) ?? null;
    if (session === null) {
      if (allowMissing) return null;
      throw new TypeError("effect admission profile is not started");
    }
    const generation = positiveInteger(
      input.generation ?? input.profileGeneration,
      "generation",
    );
    if (generation !== session.generation) {
      throw new TypeError("effect admission profile generation mismatch");
    }
    if (input.processId !== undefined && input.processId !== session.processId) {
      throw new TypeError("effect admission process identity mismatch");
    }
    if (session.contained && !allowContained) {
      throw new TypeError("effect admission profile is contained");
    }
    return session;
  }

  async #containAndProve(input, capturedTree) {
    const profileId = stableId(input.profileId, "profileId");
    const session = this.#sessions.get(profileId) ?? null;
    const freshTree = await captureLinuxProcessTree(session?.pid ?? null);
    const processTree = mergeProcessIdentities(capturedTree, freshTree);
    let containError = null;
    try {
      await this.#driver.contain(input);
    } catch (error) {
      containError = error;
    }
    await waitForLinuxProcessTreeExit(
      processTree,
      this.#containmentTimeoutMs,
    );
    this.#clearExpiry(profileId);
    const proofRecord = {
      containmentDigest: containmentDigest(processTree),
      processCount: processTree.length,
    };
    if (containError !== null) {
      // Process-tree disappearance is the effect-containment proof. Preserve a
      // non-fatal inner cleanup failure for diagnostics without weakening it.
      proofRecord.innerContainmentError = boundedError(containError);
    }
    const proof = Object.freeze(proofRecord);
    if (session !== null) {
      session.contained = true;
      session.containmentProof = proof;
    }
    return proof;
  }

  #armExpiry(profileId, expiresAtMs) {
    this.#clearExpiry(profileId);
    const arm = () => {
      const session = this.#sessions.get(profileId);
      if (!session || session.contained) return;
      const remaining = expiresAtMs - this.#clock();
      if (remaining <= 0) {
        void this.contain({
          profileId,
          generation: session.generation,
          processId: session.processId,
          reason: "profile_lease_expired",
        }).catch(() => {
          // The inner driver also enforces the physical lease. A failure to
          // record the supplementary proof remains fail-closed and observable
          // through subsequent calls.
        });
        return;
      }
      const timer = setTimeout(arm, Math.min(remaining, 2_147_000_000));
      timer.unref?.();
      this.#expiryTimers.set(profileId, timer);
    };
    arm();
  }

  #clearExpiry(profileId) {
    const timer = this.#expiryTimers.get(profileId);
    if (timer !== undefined) clearTimeout(timer);
    this.#expiryTimers.delete(profileId);
  }
}

export class AgentdBrowserChannel {
  #input;
  #output;
  #decoder = new AgentdBrowserFrameDecoder();
  #nextIncomingSequence = 1;
  #nextOutgoingSequence = 1;
  #queue = [];
  #waiters = [];
  #failed = null;
  #ended = false;

  constructor({ input, output }) {
    if (!input?.on || typeof output?.write !== "function") {
      throw new TypeError("Agentd browser channel requires readable and writable streams");
    }
    this.#input = input;
    this.#output = output;
    input.on("data", (chunk) => this.#onBytes(chunk));
    input.on("end", () => this.#onEnd());
    input.on("error", (error) => this.#fail(error));
    output.on?.("error", (error) => this.#fail(error));
  }

  async nextFrame() {
    if (this.#queue.length) return this.#queue.shift();
    if (this.#failed) throw this.#failed;
    if (this.#ended) return null;
    return new Promise((resolve, reject) => this.#waiters.push({ resolve, reject }));
  }

  send(kind, requestId, payload) {
    if (this.#failed) return Promise.reject(this.#failed);
    if (this.#ended) return Promise.reject(new Error("Agentd browser channel is closed"));
    const encoded = encodeAgentdBrowserFrame(
      buildAgentdBrowserFrame({
        sequence: this.#nextOutgoingSequence++,
        kind,
        requestId,
        payload,
      }),
    );
    return new Promise((resolve, reject) => {
      this.#output.write(encoded, (error) => {
        if (error) reject(error);
        else resolve();
      });
    });
  }

  #onBytes(chunk) {
    if (this.#failed || this.#ended) return;
    let frames;
    try {
      frames = this.#decoder.push(chunk);
    } catch (error) {
      this.#fail(error);
      return;
    }
    for (const frame of frames) {
      if (frame.sequence !== this.#nextIncomingSequence++) {
        this.#fail(new TypeError("Agentd browser input sequence is not monotonic"));
        return;
      }
      const waiter = this.#waiters.shift();
      if (waiter) {
        waiter.resolve(frame);
      } else {
        if (this.#queue.length >= MAX_QUEUED_AGENTD_FRAMES) {
          this.#fail(
            new Error("Agentd browser input queue capacity is exhausted"),
          );
          return;
        }
        this.#queue.push(frame);
      }
    }
  }

  #onEnd() {
    if (this.#failed || this.#ended) return;
    try {
      this.#decoder.end();
    } catch (error) {
      this.#fail(error);
      return;
    }
    this.#ended = true;
    for (const waiter of this.#waiters.splice(0)) waiter.resolve(null);
  }

  #fail(error) {
    if (this.#failed) return;
    this.#failed = error instanceof Error ? error : new Error(String(error));
    this.#queue.length = 0;
    for (const waiter of this.#waiters.splice(0)) waiter.reject(this.#failed);
  }
}

export class ParentFinalUseAuthority {
  #channel;
  #activeRequestId = null;

  constructor(channel) {
    if (!(channel instanceof AgentdBrowserChannel)) {
      throw new TypeError("ParentFinalUseAuthority requires AgentdBrowserChannel");
    }
    this.#channel = channel;
  }

  async withRequest(requestId, call) {
    if (this.#activeRequestId !== null) {
      throw new TypeError("browser service authority request is already active");
    }
    this.#activeRequestId = requestId;
    try {
      return await call();
    } finally {
      this.#activeRequestId = null;
    }
  }

  async withVerifiedUse(request, consumer) {
    requireRecord(request, "final-use request");
    if (this.#activeRequestId === null) {
      throw new TypeError("final-use authority may only run inside one Agentd request");
    }
    const requestId = this.#activeRequestId;
    const requestDigest = digest(request.requestDigest, "requestDigest");
    const authorityEpoch = positiveInteger(request.authorityEpoch, "authorityEpoch");
    // Final-use authority consumes immutable identity, not the live action
    // body. Avoid duplicating typed action data (notably type.text) into the
    // authority control plane.
    await this.#channel.send("authority_challenge", requestId, {
      requestDigest,
      authorityEpoch,
    });
    const enter = await this.#channel.nextFrame();
    if (!enter || enter.kind !== "authority_enter" || enter.requestId !== requestId) {
      throw new TypeError("Agentd did not enter the matching final-use fence");
    }
    const payload = requireRecord(enter.payload, "authority enter payload");
    if (payload.authorized !== true) {
      throw new TypeError("Agentd final-use authority denied browser dispatch");
    }
    const witness = Object.freeze({
      authorized: true,
      witnessDigest: digest(payload.witnessDigest, "witnessDigest"),
      authorityEpoch: positiveInteger(payload.authorityEpoch, "authorityEpoch"),
      requestDigest: digest(payload.requestDigest, "requestDigest"),
    });
    if (
      witness.requestDigest !== requestDigest ||
      witness.authorityEpoch !== authorityEpoch
    ) {
      throw new TypeError(
        "Agentd final-use witness does not bind the Browser request",
      );
    }
    let result;
    try {
      result = requireRecord(
        await consumer(witness),
        "Browser verified-use result",
      );
      validateBrowserEffectAdmission(result.admission, request);
    } catch (error) {
      if (error?.code === "BROWSER_WORKER_PRE_DISPATCH_REJECTED") {
        await this.#channel.send("dispatch_rejected", requestId, {
          requestDigest,
          witnessDigest: witness.witnessDigest,
          localDispatchCrossed: false,
        });
      } else if (error?.workerContained === true) {
        // The worker may have crossed admission before its acknowledgement was
        // observed. Conservatively report the dispatch boundary as crossed;
        // the durable identity remains indeterminate, while containment proves
        // no further effect can occur after the fence is released.
        await this.#channel.send("dispatch_boundary", requestId, {
          requestDigest,
          witnessDigest: witness.witnessDigest,
          localDispatchCrossed: true,
        });
      }
      throw error;
    }
    await this.#channel.send("dispatch_boundary", requestId, {
      requestDigest,
      witnessDigest: witness.witnessDigest,
      localDispatchCrossed: true,
    });
    return result;
  }
}

export class BrowserAgentdService {
  #host;
  #channel;
  #authority;

  constructor({ host, channel, authority }) {
    requireRecord(host, "browser host");
    for (const method of [
      "openProfile",
      "admitEffectGrant",
      "observePage",
      "navigateOrAct",
      "reconcileOperation",
      "reconcilePersistedOperation",
      "closeProfile",
    ]) {
      if (typeof host[method] !== "function") {
        throw new TypeError(`browser host.${method} is required`);
      }
    }
    if (!(channel instanceof AgentdBrowserChannel)) {
      throw new TypeError("BrowserAgentdService requires AgentdBrowserChannel");
    }
    if (!(authority instanceof ParentFinalUseAuthority)) {
      throw new TypeError("BrowserAgentdService requires ParentFinalUseAuthority");
    }
    this.#host = host;
    this.#channel = channel;
    this.#authority = authority;
  }

  async run() {
    while (true) {
      const frame = await this.#channel.nextFrame();
      if (frame === null) return;
      if (frame.kind !== "request") {
        throw new TypeError("Browser service expected an Agentd request frame");
      }
      await this.#serve(frame);
    }
  }

  async #serve(frame) {
    try {
      const payload = requireRecord(
        frame.payload,
        "Browser service request payload",
      );
      if (!SERVICE_METHODS.has(payload.method)) {
        throw new TypeError("Browser service method is not registered");
      }
      const input = requireRecord(payload.input, "Browser service input");
      let result;
      switch (payload.method) {
        case "open_profile":
          result = await this.#host.openProfile(input);
          break;
        case "admit_effect_grant":
          result = await this.#host.admitEffectGrant(input);
          break;
        case "observe_page":
          result = await this.#host.observePage(input);
          break;
        case "navigate_or_act":
          result = await this.#authority.withRequest(frame.requestId, () =>
            this.#host.navigateOrAct(input),
          );
          break;
        case "reconcile_operation":
          result = await this.#host.reconcileOperation(input);
          break;
        case "reconcile_persisted_operation":
          result = await this.#host.reconcilePersistedOperation(input);
          break;
        case "close_profile":
          result = await this.#host.closeProfile(input);
          break;
        default:
          throw new TypeError("unreachable Browser service method");
      }
      await this.#channel.send("response", frame.requestId, {
        ok: true,
        result,
      });
    } catch (error) {
      await this.#channel.send("response", frame.requestId, {
        ok: false,
        error: boundedError(error),
      });
    }
  }
}

import { spawn } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { constants } from "node:fs";
import {
  lstat,
  mkdir,
  open,
  realpath,
  rm,
} from "node:fs/promises";
import { isAbsolute, resolve } from "node:path";
import { performance } from "node:perf_hooks";

import { browserProfileArtifactPaths } from "./profile-artifacts.js";
import { OwnedBrowserChild } from "./worker-lifecycle.js";

import { GrantScopedEgressBroker } from "./egress-broker.js";
import {
  WorkerFrameDecoder,
  buildWorkerFrame,
  encodeWorkerFrame,
} from "./worker-protocol.js";

const DIGEST = /^[0-9a-f]{64}$/;
const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const MAX_WORKER_ARTIFACT_BYTES = 512 * 1024 * 1024;
const MAX_BWRAP_ARTIFACT_BYTES = 64 * 1024 * 1024;
const MAX_PRLIMIT_ARTIFACT_BYTES = 16 * 1024 * 1024;
const MAX_ABANDONED_RESPONSES = 1024;
const DEFAULT_MAX_ADDRESS_SPACE_BYTES = 8 * 1024 * 1024 * 1024;
const DEFAULT_MAX_CPU_SECONDS = 300;
const DEFAULT_MAX_OPEN_FILES = 4096;
const DEFAULT_MAX_PROCESSES = 256;
const DEFAULT_MAX_POOL_PROFILES = 16;
const MAX_POOL_PROFILES = 64;

function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function expectedDigest(value, name) {
  if (typeof value !== "string" || !DIGEST.test(value) || /^0+$/.test(value)) {
    throw new TypeError(`${name} must be a non-zero lowercase SHA-256 digest`);
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

function requestId(kind, semanticId) {
  const digest = createHash("sha256")
    .update(`${kind}\u0000${semanticId}`)
    .digest("hex");
  return `browser.${kind}.${digest.slice(0, 32)}`;
}

async function ensurePrivateProfileRoot(path) {
  await mkdir(path, { recursive: true, mode: 0o700 });
  const metadata = await lstat(path);
  if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
    throw new TypeError(
      "browser profile root must be a regular non-symlink directory",
    );
  }
  if (process.platform !== "win32" && (metadata.mode & 0o077) !== 0) {
    throw new TypeError("browser profile root permissions are too broad");
  }
  if ((await realpath(path)) !== resolve(path)) {
    throw new TypeError("browser profile root path contains a symlink");
  }
}

function abortError(message = "browser worker request aborted") {
  const error = new Error(message);
  error.name = "AbortError";
  return error;
}

async function verifyExactHostExecutable(path, expected, maximum, label) {
  if ((await realpath(path)) !== path) {
    throw new TypeError(`${label} path contains a symlink`);
  }
  const noFollow = constants.O_NOFOLLOW ?? 0;
  const handle = await open(path, constants.O_RDONLY | noFollow);
  try {
    const info = await handle.stat();
    if (!info.isFile() || info.size < 1 || info.size > maximum) {
      throw new TypeError(`${label} must be a bounded regular file`);
    }
    const bytes = await handle.readFile();
    if (sha256(bytes) !== expected) {
      throw new TypeError(`${label} digest mismatch`);
    }
  } finally {
    await handle.close();
  }
}

export class LinuxBubblewrapLauncher {
  constructor({
    bwrapPath = "/usr/bin/bwrap",
    bwrapDigest,
    prlimitPath = "/usr/bin/prlimit",
    prlimitDigest,
    maxAddressSpaceBytes = DEFAULT_MAX_ADDRESS_SPACE_BYTES,
    maxCpuSeconds = DEFAULT_MAX_CPU_SECONDS,
    maxOpenFiles = DEFAULT_MAX_OPEN_FILES,
    maxProcesses = DEFAULT_MAX_PROCESSES,
  } = {}) {
    if (process.platform !== "linux") {
      throw new TypeError("LinuxBubblewrapLauncher requires Linux");
    }
    if (!isAbsolute(bwrapPath)) throw new TypeError("bwrapPath must be absolute");
    if (!isAbsolute(prlimitPath)) throw new TypeError("prlimitPath must be absolute");
    for (const [value, name] of [
      [maxAddressSpaceBytes, "maxAddressSpaceBytes"],
      [maxCpuSeconds, "maxCpuSeconds"],
      [maxOpenFiles, "maxOpenFiles"],
      [maxProcesses, "maxProcesses"],
    ]) positiveInteger(value, name);
    this.bwrapPath = resolve(bwrapPath);
    this.bwrapDigest = expectedDigest(bwrapDigest, "bwrapDigest");
    this.prlimitPath = resolve(prlimitPath);
    this.prlimitDigest = expectedDigest(prlimitDigest, "prlimitDigest");
    this.resourceLimits = Object.freeze({
      maxAddressSpaceBytes,
      maxCpuSeconds,
      maxOpenFiles,
      maxProcesses,
    });
    this.posture = Object.freeze({
      sourceContractOnly: true,
      inheritedPrivateChannel: true,
      externalNetworkDenied: true,
      ambientEnvironmentDenied: true,
      userHomeHidden: true,
      hostFilesystemRestricted: true,
      parentDeathCleanup: true,
      resourceLimitsConfigured: true,
    });
  }

  async verify() {
    await verifyExactHostExecutable(
      this.bwrapPath,
      this.bwrapDigest,
      MAX_BWRAP_ARTIFACT_BYTES,
      "Bubblewrap launcher",
    );
    await verifyExactHostExecutable(
      this.prlimitPath,
      this.prlimitDigest,
      MAX_PRLIMIT_ARTIFACT_BYTES,
      "prlimit launcher",
    );
  }

  argv({ workerPath, profileDir }) {
    if (!isAbsolute(workerPath) || !isAbsolute(profileDir)) {
      throw new TypeError("workerPath and profileDir must be absolute");
    }
    return [
      "--unshare-all",
      "--new-session",
      "--die-with-parent",
      "--clearenv",
      "--tmpfs",
      "/",
      "--dir",
      "/usr",
      "--ro-bind-try",
      "/usr/lib",
      "/usr/lib",
      "--ro-bind-try",
      "/usr/lib64",
      "/usr/lib64",
      "--dir",
      "/usr/share",
      "--ro-bind-try",
      "/usr/share/fonts",
      "/usr/share/fonts",
      "--ro-bind-try",
      "/usr/share/fontconfig",
      "/usr/share/fontconfig",
      "--symlink",
      "usr/lib",
      "/lib",
      "--symlink",
      "usr/lib64",
      "/lib64",
      "--dir",
      "/etc",
      "--ro-bind-try",
      "/etc/ld.so.cache",
      "/etc/ld.so.cache",
      "--ro-bind-try",
      "/etc/fonts",
      "/etc/fonts",
      "--ro-bind-try",
      "/etc/ssl/certs",
      "/etc/ssl/certs",
      "--ro-bind-try",
      "/etc/ssl/openssl.cnf",
      "/etc/ssl/openssl.cnf",
      "--ro-bind-try",
      "/etc/ca-certificates.conf",
      "/etc/ca-certificates.conf",
      "--ro-bind-try",
      "/usr/share/ca-certificates",
      "/usr/share/ca-certificates",
      "--dir",
      "/var",
      "--dir",
      "/var/cache",
      "--ro-bind-try",
      "/var/cache/fontconfig",
      "/var/cache/fontconfig",
      "--tmpfs",
      "/home",
      "--tmpfs",
      "/root",
      "--tmpfs",
      "/run",
      "--tmpfs",
      "/tmp",
      "--proc",
      "/proc",
      "--dev",
      "/dev",
      "--bind",
      profileDir,
      "/hepta-profile",
      "--ro-bind",
      workerPath,
      "/hepta-worker",
      "--chdir",
      "/hepta-profile",
      "--setenv",
      "HOME",
      "/hepta-profile",
      "--setenv",
      "TMPDIR",
      "/tmp",
      "--setenv",
      "HEPTA_BROWSER_WORKER_PROTOCOL",
      "1",
      "/hepta-worker",
    ];
  }

  spawnSpec({ workerPath, profileDir }) {
    const limits = this.resourceLimits;
    return Object.freeze({
      command: this.prlimitPath,
      args: Object.freeze([
        `--as=${limits.maxAddressSpaceBytes}:${limits.maxAddressSpaceBytes}`,
        `--cpu=${limits.maxCpuSeconds}:${limits.maxCpuSeconds}`,
        `--nofile=${limits.maxOpenFiles}:${limits.maxOpenFiles}`,
        `--nproc=${limits.maxProcesses}:${limits.maxProcesses}`,
        "--",
        this.bwrapPath,
        ...this.argv({ workerPath, profileDir }),
      ]),
    });
  }

  spawn({ workerPath, profileDir }) {
    const spec = this.spawnSpec({ workerPath, profileDir });
    return spawn(spec.command, [...spec.args], {
      stdio: ["pipe", "pipe", "pipe"],
      env: {},
      shell: false,
      windowsHide: true,
    });
  }
}

class PrivateWorkerClient {
  #child;
  #sessionId;
  #generation;
  #decoder = new WorkerFrameDecoder();
  #nextOutgoingSequence = 1;
  #lastIncomingSequence = 0;
  #pending = new Map();
  #abandoned = new Set();
  #closed = false;

  constructor({ child, sessionId, generation }) {
    this.#child = child;
    this.#sessionId = sessionId;
    this.#generation = generation;
    child.stdout.on("data", (chunk) => this.#onBytes(chunk));
    child.stdout.on("end", () => {
      try {
        this.#decoder.end();
      } catch (error) {
        this.#failAll(error);
      }
    });
    child.stderr?.resume?.();
    child.stdin.on("error", (error) => this.#failAll(error));
    child.on("error", (error) => this.#failAll(error));
    child.on("exit", (code, signal) => {
      this.#closed = true;
      this.#failAll(
        new Error(
          `browser worker exited before response: code=${code} signal=${signal}`,
        ),
      );
    });
  }

  request(kind, semanticId, payload, { signal, onDispatchBoundary } = {}) {
    if (this.#closed) {
      return Promise.reject(new Error("browser worker channel is closed"));
    }
    if (signal?.aborted) return Promise.reject(abortError());
    const sequence = this.#nextOutgoingSequence++;
    const id = requestId(kind, semanticId);
    if (this.#pending.has(id) || this.#abandoned.has(id)) {
      return Promise.reject(
        new TypeError("browser worker request identity is already live"),
      );
    }
    const frame = buildWorkerFrame({
      sessionId: this.#sessionId,
      generation: this.#generation,
      sequence,
      kind,
      requestId: id,
      payload,
    });
    const encoded = encodeWorkerFrame(frame);
    return new Promise((resolve, reject) => {
      let writeStarted = false;
      const entry = {
        resolve,
        reject,
        cleanup: null,
        requestKind: kind,
        requestPayloadDigest: frame.payloadDigest,
        requestSequence: sequence,
        onDispatchBoundary,
        dispatchBoundaryObserved: false,
      };
      const abort = () => {
        if (!this.#pending.delete(id)) return;
        entry.cleanup?.();
        if (writeStarted) {
          if (this.#abandoned.size >= MAX_ABANDONED_RESPONSES) {
            this.#failAll(
              new Error("browser worker abandoned-response capacity exhausted"),
            );
            this.#child.kill("SIGKILL");
          } else {
            this.#abandoned.add(id);
          }
        }
        reject(abortError());
      };
      this.#pending.set(id, entry);
      if (signal) {
        signal.addEventListener("abort", abort, { once: true });
        entry.cleanup = () => signal.removeEventListener("abort", abort);
        if (signal.aborted) {
          abort();
          return;
        }
      }
      writeStarted = true;
      this.#child.stdin.write(encoded, (error) => {
        if (error && this.#pending.delete(id)) {
          entry.cleanup?.();
          reject(error);
        }
      });
    });
  }

  close() {
    this.#closed = true;
    this.#child.stdin.end();
    this.#failAll(new Error("browser worker channel closed"));
    this.#abandoned.clear();
  }

  #onBytes(chunk) {
    let frames;
    try {
      frames = this.#decoder.push(chunk);
    } catch (error) {
      this.#failAll(error);
      this.#child.kill("SIGKILL");
      return;
    }
    for (const frame of frames) {
      if (
        frame.sessionId !== this.#sessionId ||
        frame.generation !== this.#generation
      ) {
        this.#failAll(
          new TypeError("browser worker response crossed session or generation"),
        );
        this.#child.kill("SIGKILL");
        return;
      }
      if (frame.sequence !== this.#lastIncomingSequence + 1) {
        this.#failAll(
          new TypeError("browser worker response sequence is not monotonic"),
        );
        this.#child.kill("SIGKILL");
        return;
      }
      this.#lastIncomingSequence = frame.sequence;
      const pending = this.#pending.get(frame.requestId);
      if (!pending) {
        if (
          frame.kind === "dispatch_boundary" &&
          this.#abandoned.has(frame.requestId)
        ) {
          continue;
        }
        if (
          frame.kind === "response" &&
          this.#abandoned.delete(frame.requestId)
        ) {
          continue;
        }
        this.#failAll(
          new TypeError("browser worker frame has no pending request"),
        );
        this.#child.kill("SIGKILL");
        return;
      }
      const payload = requireRecord(frame.payload, "worker response payload");
      if (
        payload.requestKind !== pending.requestKind ||
        payload.requestPayloadDigest !== pending.requestPayloadDigest ||
        payload.requestSequence !== pending.requestSequence
      ) {
        this.#failAll(
          new TypeError("browser worker response did not bind the exact request"),
        );
        this.#child.kill("SIGKILL");
        return;
      }
      if (frame.kind === "dispatch_boundary") {
        const keys = Object.keys(payload).sort();
        const expected = [
          "localDispatchCrossed",
          "requestKind",
          "requestPayloadDigest",
          "requestSequence",
        ].sort();
        if (
          pending.requestKind !== "dispatch" ||
          pending.dispatchBoundaryObserved === true ||
          payload.localDispatchCrossed !== true ||
          keys.length !== expected.length ||
          keys.some((key, index) => key !== expected[index])
        ) {
          this.#failAll(
            new TypeError("browser worker dispatch boundary is invalid"),
          );
          this.#child.kill("SIGKILL");
          return;
        }
        pending.dispatchBoundaryObserved = true;
        try {
          pending.onDispatchBoundary?.();
        } catch (error) {
          this.#failAll(error);
          this.#child.kill("SIGKILL");
          return;
        }
        continue;
      }
      if (frame.kind !== "response") {
        this.#failAll(
          new TypeError("browser worker emitted an unexpected frame kind"),
        );
        this.#child.kill("SIGKILL");
        return;
      }

      const responseKeys = Object.keys(payload).sort();
      const expectedResponseKeys =
        payload.ok === true
          ? [
              "observation",
              "ok",
              "requestKind",
              "requestPayloadDigest",
              "requestSequence",
            ].sort()
          : payload.ok === false
            ? [
                "error",
                "ok",
                "requestKind",
                "requestPayloadDigest",
                "requestSequence",
              ].sort()
            : null;
      if (
        expectedResponseKeys === null ||
        responseKeys.length !== expectedResponseKeys.length ||
        responseKeys.some((key, index) => key !== expectedResponseKeys[index])
      ) {
        this.#failAll(
          new TypeError(
            "browser worker response payload contains missing or unknown fields",
          ),
        );
        this.#child.kill("SIGKILL");
        return;
      }

      if (
        pending.requestKind === "dispatch" &&
        pending.dispatchBoundaryObserved !== true
      ) {
        if (payload.ok === false && typeof payload.error === "string") {
          this.#pending.delete(frame.requestId);
          pending.cleanup?.();
          const error = new Error(
            `browser worker rejected dispatch before admission: ${payload.error}`,
          );
          error.name = "BrowserWorkerPreDispatchError";
          error.code = "BROWSER_WORKER_PRE_DISPATCH_REJECTED";
          error.outcomeDigest = sha256(
            Buffer.from(
              `worker-pre-dispatch\0${pending.requestPayloadDigest}\0${payload.error}`,
              "utf8",
            ),
          );
          pending.reject(error);
          continue;
        }
        this.#failAll(
          new TypeError(
            "browser worker returned dispatch result before admission boundary",
          ),
        );
        this.#child.kill("SIGKILL");
        return;
      }
      this.#pending.delete(frame.requestId);
      pending.cleanup?.();
      if (payload.ok === true) {
        pending.resolve(
          requireRecord(payload.observation, "worker observation"),
        );
      } else if (payload.ok === false && typeof payload.error === "string") {
        pending.reject(new Error(`browser worker rejected request: ${payload.error}`));
      } else {
        pending.reject(new TypeError("browser worker response payload is invalid"));
      }
    }
  }

  #failAll(error) {
    for (const pending of this.#pending.values()) {
      pending.cleanup?.();
      pending.reject(error);
    }
    this.#pending.clear();
  }
}

export class SubprocessBrowserDriver {
  supportsAbort = true;
  maxActiveProfiles = 1;
  maxOutstandingOperations = 1;

  #workerPath;
  #workerDigest;
  #profileRoot;
  #launcher;
  #child = null;
  #client = null;
  #profileDir = null;
  #profileOwnerPath = null;
  #verifiedWorkerPath = null;
  #sessionId = null;
  #generation = null;
  #processId = null;
  #persistedReconciler = null;
  #egressBroker = null;
  #allowPrivateNetworkForTests = false;
  #expiryTimer = null;
  #expiresAtMs = null;
  #expiresMonotonicMs = null;
  #ownership = null;
  #termination = null;
  #starting = false;
  #stopTask = null;
  #quarantined = false;

  constructor({
    workerPath,
    workerDigest,
    profileRoot,
    launcher,
    persistedReconciler = null,
    allowPrivateNetworkForTests = false,
  }) {
    if (!isAbsolute(workerPath)) throw new TypeError("workerPath must be absolute");
    if (!isAbsolute(profileRoot)) throw new TypeError("profileRoot must be absolute");
    requireRecord(launcher, "launcher");
    const posture = requireRecord(launcher.posture, "launcher.posture");
    if (posture.sourceContractOnly !== true) {
      throw new TypeError("launcher posture must be explicitly source-contract-only");
    }
    for (const key of [
      "inheritedPrivateChannel",
      "externalNetworkDenied",
      "ambientEnvironmentDenied",
      "userHomeHidden",
      "hostFilesystemRestricted",
      "parentDeathCleanup",
      "resourceLimitsConfigured",
    ]) {
      if (posture[key] !== true) {
        throw new TypeError(`launcher source contract does not declare ${key}`);
      }
    }
    if (typeof launcher.verify !== "function") {
      throw new TypeError("launcher.verify must be a function");
    }
    if (typeof launcher.spawn !== "function") {
      throw new TypeError("launcher.spawn must be a function");
    }
    if (typeof allowPrivateNetworkForTests !== "boolean") {
      throw new TypeError("allowPrivateNetworkForTests must be boolean");
    }
    if (
      persistedReconciler !== null &&
      typeof persistedReconciler !== "function"
    ) {
      throw new TypeError("persistedReconciler must be a function or null");
    }
    this.#workerPath = workerPath;
    this.#workerDigest = expectedDigest(workerDigest, "workerDigest");
    this.#profileRoot = profileRoot;
    this.#launcher = launcher;
    this.#persistedReconciler = persistedReconciler;
    this.#allowPrivateNetworkForTests = allowPrivateNetworkForTests;
  }

  get hasPendingCleanup() {
    return this.#child !== null || this.#ownership !== null ||
      this.#egressBroker !== null || this.#profileDir !== null ||
      this.#profileOwnerPath !== null || this.#verifiedWorkerPath !== null;
  }

  async start(input, options = {}) {
    if (this.#starting || this.#stopTask !== null || this.hasPendingCleanup) {
      throw new TypeError("browser worker is already started or still owns cleanup");
    }
    this.#starting = true;
    this.#quarantined = false;
    try {
      return await this.#start(input, options);
    } finally {
      this.#starting = false;
    }
  }

  async #start(input, { signal } = {}) {
    requireRecord(input, "browser worker start input");
    const profileId = stableId(input.profileId, "profileId");
    const principalId = stableId(input.principalId, "principalId");
    const generation = positiveInteger(input.generation, "generation");
    const manifestDigest = expectedDigest(input.manifestDigest, "manifestDigest");
    const grantDigest = expectedDigest(input.grantDigest, "grantDigest");
    const expiresAtMs = positiveInteger(input.expiresAtMs, "expiresAtMs");
    if (expiresAtMs <= Date.now()) {
      throw new TypeError("browser profile process/network lease has expired");
    }
    const expiresMonotonicMs = performance.now() + (expiresAtMs - Date.now());
    const paths = browserProfileArtifactPaths(this.#profileRoot);
    await this.#launcher.verify();
    const verifiedWorkerBytes = await this.#readVerifiedWorkerArtifact();
    await ensurePrivateProfileRoot(this.#profileRoot);
    try {
      this.#sessionId = profileId;
      this.#generation = generation;
      this.#processId = null;
      await mkdir(paths.profileDir, { mode: 0o700 });
      this.#profileDir = paths.profileDir;
      this.#egressBroker = new GrantScopedEgressBroker({
        socketPath: paths.socketPath,
        grantDigest,
        allowedOrigins: input.allowedOrigins,
        allowPrivateNetworkForTests: this.#allowPrivateNetworkForTests,
      });
      await this.#egressBroker.start();
      // Ownership metadata must not be writable through the sandbox's profile
      // bind. Keep it in the host-private profile root and expose only its
      // digest to the worker/session boundary.
      const ownerIdentity = {
        schema: "hepta.browser.profile-owner.v1",
        profileId,
        principalId,
        generation,
        manifestDigest,
        grantDigest,
      };
      await this.#writeProfileOwnerManifest(ownerIdentity, paths.profileOwnerPath);
      // Keep the verified executable outside the profile directory that is
      // mounted read/write into the sandbox. Otherwise the worker could mutate
      // the same inode through /hepta-profile even though /hepta-worker is a
      // read-only bind.
      await this.#writePrivateVerifiedWorker(verifiedWorkerBytes, paths.verifiedWorkerPath);
      this.#sessionId = profileId;
      this.#generation = generation;
      this.#child = this.#launcher.spawn({
        workerPath: this.#verifiedWorkerPath,
        profileDir: this.#profileDir,
      });
      this.#ownership = new OwnedBrowserChild(this.#child);
      if (
        !this.#child?.stdin ||
        !this.#child?.stdout ||
        typeof this.#child.on !== "function"
      ) {
        throw new TypeError(
          "launcher did not return a pipe-connected child process",
        );
      }
      this.#processId = `servo.pid.${this.#child.pid}.${randomUUID()}`;
      this.#client = new PrivateWorkerClient({
        child: this.#child,
        sessionId: this.#sessionId,
        generation: this.#generation,
      });
      const workerInput = { ...input };
      delete workerInput.expiresAtMs;
      const observed = await this.#client.request(
        "start",
        `${profileId}.${generation}`,
        workerInput,
        { signal },
      );
      if (observed.started !== true) {
        throw new TypeError("worker did not acknowledge start");
      }
      if (signal?.aborted || Date.now() >= expiresAtMs || performance.now() >= expiresMonotonicMs) {
        throw abortError("browser profile lease expired or startup was aborted");
      }
      this.#armExpiry(expiresAtMs, expiresMonotonicMs);
      return {
        started: true,
        processId: this.#processId,
        profileOwnerDigest: sha256(Buffer.from(JSON.stringify(ownerIdentity), "utf8")),
        // Owner-private composition metadata: BrowserProfileHost publishes only
        // the checked identity receipt, never this filesystem path on the wire.
        privateProfileDirectory: this.#profileDir,
      };
    } catch (error) {
      // A failed launch still owns every acquired process/socket/path. Cleanup
      // failure keeps those handles in this driver and the pool reservation.
      try {
        await this.#terminateOwnedResources();
        await this.#cleanupProfile();
      } catch (cleanupError) {
        throw new AggregateError([error, cleanupError], "browser startup failed; cleanup ownership retained");
      }
      this.#processId = null;
      throw error;
    }
  }

  async observe(input, { signal } = {}) {
    this.#requireSession(input);
    return this.#client.request("observe", `page.${input.profileId}`, input, {
      signal,
    });
  }

  async dispatch(input, { signal } = {}) {
    this.#requireSession(input);
    let crossed = false;
    let resolveBoundary;
    const boundary = new Promise((resolve) => {
      resolveBoundary = resolve;
    });

    const response = this.#client.request(
      "dispatch",
      input.operationId,
      input,
      {
        signal,
        onDispatchBoundary: () => {
          if (crossed) return;
          crossed = true;
          resolveBoundary();
        },
      },
    );
    let earlyError = null;
    const settled = response.then(
      () => "resolved",
      (error) => {
        earlyError = error;
        return "rejected";
      },
    );
    const first = await Promise.race([
      boundary.then(() => "boundary"),
      settled,
    ]);
    if (first === "rejected" && !crossed) {
      if (earlyError?.code !== "BROWSER_WORKER_PRE_DISPATCH_REJECTED") {
        await this.#containBeforeDispatchBoundary();
      }
      throw earlyError;
    }
    if (first === "resolved" && !crossed) {
      await this.#containBeforeDispatchBoundary();
      throw new TypeError(
        "browser worker settled dispatch before admission boundary",
      );
    }
    // Final-use authority is released at the worker admission boundary, but
    // retain the bound worker response so the Browser owner can durably record
    // a terminal local observation without holding the authority fence.
    return {
      terminalObserved: false,
      settlement: response,
    };
  }
  async reconcile(input, { signal } = {}) {
    this.#requireSession(input);
    return this.#client.request("reconcile", input.operationId, input, { signal });
  }

  async reconcilePersisted(input, { signal } = {}) {
    requireRecord(input, "persisted browser reconciliation input");
    if (signal?.aborted) {
      throw signal.reason instanceof Error ? signal.reason : abortError();
    }
    if (this.#persistedReconciler === null) {
      return Object.freeze({
        terminalObserved: false,
        observationReason: "persisted_reconciler_unavailable",
      });
    }
    const observed = requireRecord(
      await this.#persistedReconciler(input, { signal }),
      "persisted browser reconciliation observation",
    );
    if (
      observed.operationId !== input.operationId ||
      expectedDigest(observed.requestDigest, "persisted observation requestDigest") !==
        expectedDigest(input.requestDigest, "persisted input requestDigest") ||
      expectedDigest(observed.semanticDigest, "persisted observation semanticDigest") !==
        expectedDigest(input.semanticDigest, "persisted input semanticDigest")
    ) {
      throw new TypeError(
        "persisted reconciler observation did not bind the exact durable operation",
      );
    }
    return observed;
  }

  async contain(input) {
    if (this.#starting) throw new Error("browser worker is starting; cancel startup first");
    this.#requireIdentity(input);
    await this.#terminateOwnedResources();
    return { contained: true, processExitObserved: true };
  }

  async stop(input, options = {}) {
    if (this.#starting) throw new Error("browser worker is starting; cancel startup first");
    this.#requireIdentity(input);
    if (this.#stopTask !== null) return this.#stopTask;
    this.#stopTask = this.#stopOwned(input, options);
    try { return await this.#stopTask; }
    finally { this.#stopTask = null; }
  }

  async #stopOwned(input, { signal } = {}) {
    const graceful = this.#child && this.#client && !this.#quarantined;
    this.#quarantined = true;
    this.#clearExpiryTimer();
    // The protocol stop is best-effort bounded graceful shutdown. Its ACK is
    // not process exit; every path still waits for owned process/network exit.
    if (graceful) {
      const controller = new AbortController();
      const abort = () => controller.abort();
      signal?.addEventListener("abort", abort, { once: true });
      if (signal?.aborted) abort();
      const timer = setTimeout(abort, 1000);
      try {
        await this.#client.request(
          "stop", `${input.profileId}.${input.generation ?? input.profileGeneration}`,
          input, { signal: controller.signal },
        );
      } catch {
        // Observed forced termination below can establish stopped even when
        // a broken control channel cannot supply a graceful ACK.
      } finally {
        clearTimeout(timer);
        signal?.removeEventListener("abort", abort);
      }
    }
    await this.#terminateOwnedResources();
    await this.#cleanupProfile();
    return { stopped: true };
  }

  #armExpiry(expiresAtMs, expiresMonotonicMs) {
    this.#clearExpiryTimer();
    this.#expiresAtMs = expiresAtMs;
    this.#expiresMonotonicMs = expiresMonotonicMs;
    const arm = () => {
      if (!this.#child || this.#expiresAtMs === null) return;
      const remaining = Math.min(
        this.#expiresAtMs - Date.now(),
        this.#expiresMonotonicMs - performance.now(),
      );
      if (remaining <= 0) {
        this.#quarantined = true;
        // Keep failed cleanup visible through retained ownership; never emit
        // an unhandled timer rejection or free a live pool slot on failure.
        void this.#terminateOwnedResources().catch(() => {});
        return;
      }
      this.#expiryTimer = setTimeout(arm, Math.min(remaining, 2_147_000_000));
      this.#expiryTimer.unref?.();
    };
    arm();
  }

  #clearExpiryTimer() {
    if (this.#expiryTimer !== null) clearTimeout(this.#expiryTimer);
    this.#expiryTimer = null;
    this.#expiresAtMs = null;
    this.#expiresMonotonicMs = null;
  }

  async #terminateOwnedResources() {
    if (this.#termination !== null) return this.#termination;
    this.#quarantined = true;
    this.#clearExpiryTimer();
    this.#termination = this.#terminate();
    try {
      return await this.#termination;
    } finally {
      this.#termination = null;
    }
  }

  async #terminate() {
    try { this.#client?.close(); } catch { /* Process termination remains mandatory. */ }
    this.#client = null; // No further effect can enter this channel.
    const process = this.#ownership;
    const broker = this.#egressBroker;
    const results = await Promise.allSettled([
      process ? process.terminate() : this.#child === null
        ? Promise.resolve() : Promise.reject(new Error("acquired worker has no verifiable exit owner")),
      broker?.close(),
    ]);
    if (results[0].status === "fulfilled") {
      this.#child = null;
      this.#ownership = null;
    }
    if (results[1].status === "fulfilled") this.#egressBroker = null;
    const errors = results.filter(result => result.status === "rejected").map(result => result.reason);
    if (errors.length) {
      const error = new AggregateError(errors, "browser containment incomplete; ownership retained");
      error.code = "BROWSER_CONTAINMENT_UNPROVED";
      throw error;
    }
  }

  async #readVerifiedWorkerArtifact() {
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const handle = await open(this.#workerPath, constants.O_RDONLY | noFollow);
    try {
      const info = await handle.stat();
      if (
        !info.isFile() ||
        info.size < 1 ||
        info.size > MAX_WORKER_ARTIFACT_BYTES
      ) {
        throw new TypeError("browser worker artifact must be a bounded regular file");
      }
      const bytes = await handle.readFile();
      if (sha256(bytes) !== this.#workerDigest) {
        throw new TypeError("browser worker artifact digest mismatch");
      }
      return bytes;
    } finally {
      await handle.close();
    }
  }

  async #writeProfileOwnerManifest(identity, path) {
    const body = Buffer.from(`${JSON.stringify(identity)}\n`, "utf8");
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const flags =
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | noFollow;
    const handle = await open(path, flags, 0o600);
    this.#profileOwnerPath = path; // Only an acquired file may be cleaned up.
    try {
      await handle.writeFile(body);
      await handle.sync();
      const info = await handle.stat();
      if (!info.isFile() || info.size !== body.length) {
        throw new TypeError(
          "profile owner manifest is not a regular exact-length file",
        );
      }
    } finally {
      await handle.close();
    }
  }

  async #writePrivateVerifiedWorker(bytes, path) {
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const flags =
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | noFollow;
    const handle = await open(path, flags, 0o500);
    this.#verifiedWorkerPath = path;
    try {
      await handle.writeFile(bytes);
      await handle.sync();
      const info = await handle.stat();
      if (!info.isFile() || info.size !== bytes.length) {
        throw new TypeError(
          "verified browser worker copy is not a regular exact-length file",
        );
      }
    } finally {
      await handle.close();
    }
  }

  #requireIdentity(input) {
    requireRecord(input, "browser worker identity");
    const profileId = stableId(input.profileId, "profileId");
    const generation = positiveInteger(input.generation ?? input.profileGeneration, "generation");
    if (profileId !== this.#sessionId || generation !== this.#generation) {
      throw new TypeError("browser worker session or generation mismatch");
    }
    if (input.processId !== undefined && input.processId !== this.#processId) {
      throw new TypeError("browser worker process identity mismatch");
    }
  }

  #requireSession(input) {
    this.#requireIdentity(input);
    if (this.#expiresAtMs !== null &&
        (Date.now() >= this.#expiresAtMs || performance.now() >= this.#expiresMonotonicMs)) {
      this.#quarantined = true;
      void this.#terminateOwnedResources().catch(() => {});
    }
    if (this.#quarantined || !this.#child || !this.#client) {
      throw new TypeError("browser worker is not started or is quarantined");
    }
  }

  async #containBeforeDispatchBoundary() {
    await this.#terminateOwnedResources();
  }

  async #cleanupProfile() {
    // Only retire a path after its actual deletion succeeds. A retry needs the
    // same remaining handles, not a newly minted profile generation.
    if (this.#child || this.#ownership || this.#egressBroker) {
      throw new Error("cannot delete profile storage before owned resources close");
    }
    const errors = [];
    for (const [path, clear, recursive] of [
      [this.#profileOwnerPath, () => { this.#profileOwnerPath = null; }, false],
      [this.#verifiedWorkerPath, () => { this.#verifiedWorkerPath = null; }, false],
      [this.#profileDir, () => { this.#profileDir = null; }, true],
    ]) {
      if (!path) continue;
      try { await rm(path, { recursive, force: true }); clear(); }
      catch (error) { errors.push(error); }
    }
    if (errors.length) throw new AggregateError(errors, "profile filesystem cleanup remains owned");
  }
}


export class PooledSubprocessBrowserDriver {
  supportsAbort = true;
  maxOutstandingOperations = 1;
  maxActiveProfiles;

  #config;
  #sessions = new Map();
  #starting = new Set();
  #recoveryDriver;

  constructor({
    workerPath,
    workerDigest,
    profileRoot,
    launcher,
    persistedReconciler = null,
    allowPrivateNetworkForTests = false,
    maxProfiles = DEFAULT_MAX_POOL_PROFILES,
  }) {
    positiveInteger(maxProfiles, "maxProfiles");
    if (maxProfiles > MAX_POOL_PROFILES) {
      throw new TypeError("maxProfiles exceeds the Browser worker-pool ceiling");
    }
    this.maxActiveProfiles = maxProfiles;
    this.#config = {
      workerPath,
      workerDigest,
      profileRoot,
      launcher,
      persistedReconciler,
      allowPrivateNetworkForTests,
    };
    this.#recoveryDriver = new SubprocessBrowserDriver(this.#config);
  }

  async start(input, options = {}) {
    requireRecord(input, "browser worker start input");
    const profileId = stableId(input.profileId, "profileId");
    const generation = positiveInteger(input.generation, "generation");
    if (this.#sessions.has(profileId) || this.#starting.has(profileId)) {
      throw new TypeError("browser worker profile is already started or starting");
    }
    if (this.#sessions.size + this.#starting.size >= this.maxActiveProfiles) {
      const error = new Error("browser worker pool capacity is exhausted");
      error.name = "BrowserBackpressureError";
      error.code = "BROWSER_PROFILE_CAPACITY";
      throw error;
    }
    this.#starting.add(profileId);
    const driver = new SubprocessBrowserDriver(this.#config);
    try {
      const observed = await driver.start(input, options);
      this.#sessions.set(profileId, {
        driver,
        generation,
        processId: observed.processId,
      });
      return observed;
    } catch (error) {
      if (driver.hasPendingCleanup) {
        this.#sessions.set(profileId, { driver, generation, processId: null, cleanupOnly: true });
      }
      throw error;
    } finally {
      this.#starting.delete(profileId);
    }
  }

  observe(input, options = {}) {
    return this.#session(input).driver.observe(input, options);
  }

  dispatch(input, options = {}) {
    return this.#session(input).driver.dispatch(input, options);
  }

  reconcile(input, options = {}) {
    return this.#session(input).driver.reconcile(input, options);
  }

  reconcilePersisted(input, options = {}) {
    return this.#recoveryDriver.reconcilePersisted(input, options);
  }

  async contain(input) {
    requireRecord(input, "browser worker containment input");
    const profileId = stableId(input.profileId, "profileId");
    if (this.#starting.has(profileId)) throw new Error("browser worker is starting; cancel startup first");
    const session = this.#sessions.get(profileId);
    if (!session) return { contained: true };
    this.#validateSessionIdentity(input, session);
    return session.driver.contain(input);
  }

  async stop(input, options = {}) {
    requireRecord(input, "browser worker stop input");
    const profileId = stableId(input.profileId, "profileId");
    if (this.#starting.has(profileId)) throw new Error("browser worker is starting; cancel startup first");
    const session = this.#sessions.get(profileId);
    if (!session) return { stopped: true };
    this.#validateSessionIdentity(input, session);
    const result = await session.driver.stop(input, options);
    if (result.stopped !== true || session.driver.hasPendingCleanup) {
      throw new Error("browser pool cannot release an unclosed owner");
    }
    this.#sessions.delete(profileId);
    return result;
  }

  #session(input) {
    requireRecord(input, "browser worker request");
    const profileId = stableId(input.profileId, "profileId");
    const session = this.#sessions.get(profileId);
    if (!session) throw new TypeError("browser worker profile is not started");
    if (session.cleanupOnly) throw new TypeError("browser worker profile is quarantined for cleanup");
    this.#validateSessionIdentity(input, session);
    return session;
  }

  #validateSessionIdentity(input, session) {
    const generation = input.generation ?? input.profileGeneration;
    if (generation !== session.generation) {
      throw new TypeError("browser worker profile generation mismatch");
    }
    if (input.processId !== undefined && input.processId !== session.processId) {
      throw new TypeError("browser worker process identity mismatch");
    }
  }
}

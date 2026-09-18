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
import { isAbsolute, join, resolve } from "node:path";

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
        payload.requestPayloadDigest !== pending.requestPayloadDigest
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

  constructor({ workerPath, workerDigest, profileRoot, launcher }) {
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
    this.#workerPath = workerPath;
    this.#workerDigest = expectedDigest(workerDigest, "workerDigest");
    this.#profileRoot = profileRoot;
    this.#launcher = launcher;
  }

  async start(input, { signal } = {}) {
    if (this.#child) throw new TypeError("browser worker is already started");
    requireRecord(input, "browser worker start input");
    const profileId = stableId(input.profileId, "profileId");
    const principalId = stableId(input.principalId, "principalId");
    const generation = positiveInteger(input.generation, "generation");
    const manifestDigest = expectedDigest(input.manifestDigest, "manifestDigest");
    const grantDigest = expectedDigest(input.grantDigest, "grantDigest");
    await this.#launcher.verify();
    const verifiedWorkerBytes = await this.#readVerifiedWorkerArtifact();
    await ensurePrivateProfileRoot(this.#profileRoot);
    try {
      this.#profileDir = join(
        this.#profileRoot,
        `${profileId}.${generation}.${randomUUID()}`,
      );
      await mkdir(this.#profileDir, { mode: 0o700 });
    this.#profileOwnerPath = join(
      this.#profileDir,
      ".hepta-profile-owner.json",
    );
    const ownerIdentity = {
      schema: "hepta.browser.profile-owner.v1",
      profileId,
      principalId,
      generation,
      manifestDigest,
      grantDigest,
    };
    await this.#writeProfileOwnerManifest(ownerIdentity);
    // Keep the verified executable outside the profile directory that is
    // mounted read/write into the sandbox. Otherwise the worker could mutate
    // the same inode through /hepta-profile even though /hepta-worker is a
    // read-only bind.
    this.#verifiedWorkerPath = join(
      this.#profileRoot,
      `.hepta-verified-worker.${profileId}.${generation}.${randomUUID()}`,
    );
    await this.#writePrivateVerifiedWorker(verifiedWorkerBytes);
      this.#sessionId = profileId;
      this.#generation = generation;
      this.#child = this.#launcher.spawn({
        workerPath: this.#verifiedWorkerPath,
        profileDir: this.#profileDir,
      });
      if (
        !this.#child?.stdin ||
        !this.#child?.stdout ||
        typeof this.#child.on !== "function"
      ) {
        throw new TypeError(
          "launcher did not return a pipe-connected child process",
        );
      }
      this.#processId = `servo.pid.${this.#child.pid}`;
      this.#client = new PrivateWorkerClient({
        child: this.#child,
        sessionId: this.#sessionId,
        generation: this.#generation,
      });
      const observed = await this.#client.request(
        "start",
        `${profileId}.${generation}`,
        input,
        { signal },
      );
      if (observed.started !== true) {
        throw new TypeError("worker did not acknowledge start");
      }
      return {
        started: true,
        processId: this.#processId,
        profileOwnerDigest: sha256(Buffer.from(JSON.stringify(ownerIdentity), "utf8")),
      };
    } catch (error) {
      this.#child?.kill?.("SIGKILL");
      await this.#cleanupProfile();
      this.#child = null;
      this.#client = null;
      this.#sessionId = null;
      this.#generation = null;
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
        this.#containBeforeDispatchBoundary();
      }
      throw earlyError;
    }
    if (first === "resolved" && !crossed) {
      this.#containBeforeDispatchBoundary();
      throw new TypeError(
        "browser worker settled dispatch before admission boundary",
      );
    }
    response.catch(() => {});
    return { terminalObserved: false };
  }
  async reconcile(input, { signal } = {}) {
    this.#requireSession(input);
    return this.#client.request("reconcile", input.operationId, input, { signal });
  }

  async contain(input) {
    this.#requireSession(input);
    this.#client?.close();
    this.#child?.kill?.("SIGKILL");
    this.#client = null;
    this.#child = null;
    return { contained: true };
  }

  async stop(input, { signal } = {}) {
    const generation = input.generation ?? input.profileGeneration;
    if (
      input.profileId !== this.#sessionId ||
      generation !== this.#generation
    ) {
      throw new TypeError("browser worker session or generation mismatch");
    }
    if (!this.#child || !this.#client) {
      await this.#cleanupProfile();
      return { stopped: true };
    }
    this.#requireSession(input);
    try {
      const observed = await this.#client.request(
        "stop",
        `${input.profileId}.${input.generation}`,
        input,
        { signal },
      );
      if (observed.stopped !== true) {
        throw new TypeError("worker did not acknowledge stop");
      }
      return { stopped: true };
    } finally {
      this.#client?.close();
      this.#child?.kill?.("SIGTERM");
      this.#client = null;
      this.#child = null;
      await this.#cleanupProfile();
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

  async #writeProfileOwnerManifest(identity) {
    const body = Buffer.from(`${JSON.stringify(identity)}\n`, "utf8");
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const flags =
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | noFollow;
    const handle = await open(this.#profileOwnerPath, flags, 0o600);
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

  async #writePrivateVerifiedWorker(bytes) {
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const flags =
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | noFollow;
    const handle = await open(this.#verifiedWorkerPath, flags, 0o500);
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

  #requireSession(input) {
    if (!this.#child || !this.#client) {
      throw new TypeError("browser worker is not started");
    }
    const generation = input.generation ?? input.profileGeneration;
    if (input.profileId !== this.#sessionId || generation !== this.#generation) {
      throw new TypeError("browser worker session or generation mismatch");
    }
    if (input.processId !== undefined && input.processId !== this.#processId) {
      throw new TypeError("browser worker process identity mismatch");
    }
  }

  #containBeforeDispatchBoundary() {
    const client = this.#client;
    const child = this.#child;
    this.#client = null;
    this.#child = null;
    client?.close();
    child?.kill?.("SIGKILL");
  }

  async #cleanupProfile() {
    const profileDir = this.#profileDir;
    const verifiedWorkerPath = this.#verifiedWorkerPath;
    this.#profileDir = null;
    this.#profileOwnerPath = null;
    this.#verifiedWorkerPath = null;
    if (verifiedWorkerPath) {
      await rm(verifiedWorkerPath, { force: true });
    }
    if (profileDir) {
      await rm(profileDir, { recursive: true, force: true });
    }
  }
}

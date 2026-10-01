import { spawn } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { constants } from "node:fs";
import { mkdir, open, rm } from "node:fs/promises";
import { isAbsolute, join, relative, sep } from "node:path";

import {
  WorkerFrameDecoder,
  buildWorkerFrame,
  encodeWorkerFrame,
} from "./worker-protocol.js";
import { positiveInteger, stableId } from "./runtime-contract.js";
import { ensurePrivateWorkerProfileRoot } from "./worker-profile.js";
import { readBoundedWorkerArtifact } from "./worker-artifact.js";

const DIGEST = /^[0-9a-f]{64}$/;
const MAX_WORKER_ARTIFACT_BYTES = 512 * 1024 * 1024;
const MAX_ABANDONED_RESPONSES = 1024;
const MAX_PENDING_REQUESTS = 1024;

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
  if (typeof value !== "string" || !DIGEST.test(value)) {
    throw new TypeError(`${name} must be a lowercase SHA-256 digest`);
  }
  return value;
}

function requestId(kind, semanticId) {
  const digest = createHash("sha256")
    .update(`${kind}\u0000${semanticId}`)
    .digest("hex");
  return `browser.${kind}.${digest.slice(0, 32)}`;
}

function abortError(message = "browser worker request aborted") {
  const error = new Error(message);
  error.name = "AbortError";
  return error;
}

export class LinuxBubblewrapLauncher {
  constructor({ bwrapPath = "/usr/bin/bwrap" } = {}) {
    if (process.platform !== "linux") {
      throw new TypeError("LinuxBubblewrapLauncher requires Linux");
    }
    if (!isAbsolute(bwrapPath))
      throw new TypeError("bwrapPath must be absolute");
    this.bwrapPath = bwrapPath;
    this.posture = Object.freeze({
      inheritedPrivateChannel: true,
      externalNetworkDenied: true,
      ambientEnvironmentDenied: true,
      userHomeHidden: true,
      hostFilesystemRestricted: true,
      parentDeathCleanup: true,
    });
  }

  argv({ workerPath, profileDir }) {
    if (!isAbsolute(workerPath) || !isAbsolute(profileDir)) {
      throw new TypeError("workerPath and profileDir must be absolute");
    }
    const workerRelativeToProfile = relative(profileDir, workerPath);
    if (
      workerRelativeToProfile === "" ||
      (!isAbsolute(workerRelativeToProfile) &&
        workerRelativeToProfile !== ".." &&
        !workerRelativeToProfile.startsWith(`..${sep}`))
    ) {
      throw new TypeError(
        "verified worker artifact must be outside the writable profile",
      );
    }
    return [
      "--unshare-all",
      "--new-session",
      "--die-with-parent",
      "--clearenv",
      // Start from an empty root and expose only the immutable runtime closure
      // needed by a dynamically linked worker. General host executables,
      // /usr/local, service data and credential roots are deliberately absent.
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
      "/etc/ssl",
      "/etc/ssl",
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

  spawn({ workerPath, profileDir }) {
    return spawn(this.bwrapPath, this.argv({ workerPath, profileDir }), {
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
        this.#failAll(new Error("browser worker response channel ended"));
      } catch (error) {
        this.#failAll(error);
      }
      child.kill("SIGKILL");
    });
    child.stdout.on("close", () => {
      this.#failAll(new Error("browser worker response channel closed"));
      child.kill("SIGKILL");
    });
    for (const stream of [child.stdin, child.stdout, child.stderr].filter(
      Boolean,
    )) {
      stream.on("error", (error) => {
        this.#failAll(error);
        child.kill("SIGKILL");
      });
    }
    // Diagnostics are deliberately discarded so a full stderr pipe cannot
    // stall the private response channel or accumulate retained log data.
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

  request(kind, semanticId, payload, { signal, onDispatched } = {}) {
    if (this.#closed)
      return Promise.reject(new Error("browser worker channel is closed"));
    if (signal?.aborted) return Promise.reject(abortError());
    if (this.#pending.size >= MAX_PENDING_REQUESTS) {
      return Promise.reject(
        new TypeError("browser worker pending-request capacity exhausted"),
      );
    }
    const id = requestId(kind, semanticId);
    if (this.#pending.has(id) || this.#abandoned.has(id)) {
      return Promise.reject(
        new TypeError("browser worker request identity is already live"),
      );
    }
    const frame = buildWorkerFrame({
      sessionId: this.#sessionId,
      generation: this.#generation,
      sequence: this.#nextOutgoingSequence,
      kind,
      requestId: id,
      payload,
    });
    const encoded = encodeWorkerFrame(frame);
    this.#nextOutgoingSequence += 1;
    return new Promise((resolve, reject) => {
      let writeStarted = false;
      const entry = { resolve, reject, cleanup: null };
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
        if (error) {
          if (this.#pending.delete(id)) {
            entry.cleanup?.();
            reject(error);
          }
          return;
        }
        try {
          onDispatched?.();
        } catch (callbackError) {
          if (this.#pending.delete(id)) {
            entry.cleanup?.();
            reject(callbackError);
          }
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
    if (this.#closed) return;
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
          new TypeError(
            "browser worker response crossed session or generation",
          ),
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
      if (frame.kind !== "response") {
        this.#failAll(
          new TypeError(
            "browser worker emitted an unexpected non-response frame",
          ),
        );
        this.#child.kill("SIGKILL");
        return;
      }
      const pending = this.#pending.get(frame.requestId);
      if (!pending) {
        if (this.#abandoned.delete(frame.requestId)) continue;
        this.#failAll(
          new TypeError("browser worker response has no pending request"),
        );
        this.#child.kill("SIGKILL");
        return;
      }
      try {
        const payload = requireRecord(frame.payload, "worker response payload");
        if (payload.ok === true) {
          const observation = requireRecord(
            payload.observation,
            "worker observation",
          );
          this.#pending.delete(frame.requestId);
          pending.cleanup?.();
          pending.resolve(observation);
        } else if (payload.ok === false && typeof payload.error === "string") {
          this.#pending.delete(frame.requestId);
          pending.cleanup?.();
          pending.reject(
            new Error(`browser worker rejected request: ${payload.error}`),
          );
        } else {
          throw new TypeError("browser worker response payload is invalid");
        }
      } catch (error) {
        this.#failAll(error);
        this.#child.kill("SIGKILL");
        return;
      }
    }
  }

  #failAll(error) {
    this.#closed = true;
    this.#abandoned.clear();
    for (const pending of this.#pending.values()) {
      pending.cleanup?.();
      pending.reject(error);
    }
    this.#pending.clear();
  }
}

export class SubprocessBrowserDriver {
  #workerPath;
  #workerDigest;
  #profileRoot;
  #launcher;
  #child = null;
  #client = null;
  #profileDir = null;
  #artifactDir = null;
  #verifiedWorkerPath = null;
  #sessionId = null;
  #generation = null;
  #processId = null;
  #starting = false;
  #shutdownRequested = false;

  constructor({ workerPath, workerDigest, profileRoot, launcher }) {
    if (!isAbsolute(workerPath))
      throw new TypeError("workerPath must be absolute");
    if (!isAbsolute(profileRoot))
      throw new TypeError("profileRoot must be absolute");
    requireRecord(launcher, "launcher");
    const posture = requireRecord(launcher.posture, "launcher.posture");
    for (const key of [
      "inheritedPrivateChannel",
      "externalNetworkDenied",
      "ambientEnvironmentDenied",
      "userHomeHidden",
      "hostFilesystemRestricted",
      "parentDeathCleanup",
    ]) {
      if (posture[key] !== true)
        throw new TypeError(`launcher posture does not enforce ${key}`);
    }
    if (typeof launcher.spawn !== "function")
      throw new TypeError("launcher.spawn must be a function");
    this.#workerPath = workerPath;
    this.#workerDigest = expectedDigest(workerDigest, "workerDigest");
    this.#profileRoot = profileRoot;
    this.#launcher = launcher;
  }

  async start(input, { signal } = {}) {
    if (this.#child || this.#starting)
      throw new TypeError("browser worker is already started or starting");
    requireRecord(input, "start input");
    const sessionId = stableId(input.profileId, "profileId");
    const generation = positiveInteger(input.generation, "generation");
    if (signal?.aborted) throw abortError();
    this.#starting = true;
    this.#shutdownRequested = false;
    try {
      const verifiedWorkerBytes = await this.#readVerifiedWorkerArtifact();
      if (this.#shutdownRequested)
        throw abortError("browser worker startup was shut down");
      this.#profileRoot = await ensurePrivateWorkerProfileRoot(
        this.#profileRoot,
      );
      this.#profileDir = join(
        this.#profileRoot,
        `${sessionId}.${generation}.${randomUUID()}`,
      );
      await mkdir(this.#profileDir, { mode: 0o700 });
      this.#artifactDir = `${this.#profileDir}.artifact`;
      await mkdir(this.#artifactDir, { mode: 0o700 });
      this.#verifiedWorkerPath = join(this.#artifactDir, ".verified-worker");
      await this.#writePrivateVerifiedWorker(verifiedWorkerBytes);
      if (signal?.aborted || this.#shutdownRequested) throw abortError();
      this.#sessionId = sessionId;
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
      this.#client = new PrivateWorkerClient({
        child: this.#child,
        sessionId: this.#sessionId,
        generation: this.#generation,
      });
      this.#processId = `servo.pid.${positiveInteger(this.#child.pid, "worker pid")}`;
      const observed = await this.#client.request(
        "start",
        `${input.profileId}.${input.generation}`,
        input,
        { signal },
      );
      if (observed.started !== true)
        throw new TypeError("worker did not acknowledge start");
      return { started: true, processId: this.#processId };
    } catch (error) {
      this.#child?.kill?.("SIGKILL");
      await this.#cleanupProfile();
      this.#child = null;
      this.#client = null;
      throw error;
    } finally {
      this.#starting = false;
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
        onDispatched: () => {
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
    if (first === "rejected" && !crossed) throw earlyError;
    // A complete response necessarily proves the request bytes crossed the
    // local worker channel even if a stream implementation delivered the
    // response before invoking the write callback.
    if (first === "resolved" && !crossed) {
      crossed = true;
      resolveBoundary();
    }
    // Keep the private response handler alive so a late worker reply cannot
    // become an unhandled rejection or poison the framed channel. External
    // terminality is intentionally obtained through reconcile().
    response.catch(() => {});
    return { terminalObserved: false };
  }

  async reconcile(input, { signal } = {}) {
    this.#requireSession(input);
    return this.#client.request("reconcile", input.operationId, input, {
      signal,
    });
  }

  async stop(input, { signal } = {}) {
    this.#requireSession(input);
    try {
      const observed = await this.#client.request(
        "stop",
        `${input.profileId}.${input.generation}`,
        input,
        { signal },
      );
      if (observed.stopped !== true)
        throw new TypeError("worker did not acknowledge stop");
      return { stopped: true };
    } finally {
      await this.shutdown();
    }
  }

  async shutdown() {
    this.#shutdownRequested = true;
    this.#client?.close();
    this.#child?.kill?.("SIGKILL");
    this.#client = null;
    this.#child = null;
    await this.#cleanupProfile();
  }

  async #readVerifiedWorkerArtifact() {
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const handle = await open(
      this.#workerPath,
      constants.O_RDONLY | noFollow | (constants.O_NONBLOCK ?? 0),
    );
    try {
      const info = await handle.stat();
      if (
        !info.isFile() ||
        info.size < 1 ||
        info.size > MAX_WORKER_ARTIFACT_BYTES
      ) {
        throw new TypeError(
          "browser worker artifact must be a bounded regular file",
        );
      }
      const bytes = await readBoundedWorkerArtifact(
        handle,
        MAX_WORKER_ARTIFACT_BYTES,
      );
      if (sha256(bytes) !== this.#workerDigest) {
        throw new TypeError("browser worker artifact digest mismatch");
      }
      return bytes;
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
    if (this.#starting || !this.#child || !this.#client)
      throw new TypeError("browser worker is not started");
    const generation = input.generation ?? input.profileGeneration;
    if (
      input.profileId !== this.#sessionId ||
      generation !== this.#generation
    ) {
      throw new TypeError("browser worker session or generation mismatch");
    }
    if (input.processId !== undefined && input.processId !== this.#processId) {
      throw new TypeError("browser worker process identity mismatch");
    }
  }

  async #cleanupProfile() {
    const paths = [this.#profileDir, this.#artifactDir].filter(Boolean);
    this.#profileDir = null;
    this.#artifactDir = null;
    this.#verifiedWorkerPath = null;
    await Promise.all(
      paths.map((path) => rm(path, { recursive: true, force: true })),
    );
  }
}

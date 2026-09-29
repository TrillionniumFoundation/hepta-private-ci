import { spawn } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { constants } from "node:fs";
import { mkdir, open, rm } from "node:fs/promises";
import { isAbsolute, join } from "node:path";

import { PrivateWorkerClient } from "./worker-client.js";
import { OwnedWorkerProcess } from "./worker-process.js";
import { buildWorkerFrame, encodeWorkerFrame } from "./worker-protocol.js";

const DIGEST = /^[0-9a-f]{64}$/;
const MAX_WORKER_ARTIFACT_BYTES = 512 * 1024 * 1024;

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

export class LinuxBubblewrapLauncher {
  constructor({ bwrapPath = "/usr/bin/bwrap" } = {}) {
    if (process.platform !== "linux") {
      throw new TypeError("LinuxBubblewrapLauncher requires Linux");
    }
    if (!isAbsolute(bwrapPath)) throw new TypeError("bwrapPath must be absolute");
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
    return [
      "--unshare-all",
      "--new-session",
      "--die-with-parent",
      "--clearenv",
      // Start from an empty root and expose only the immutable runtime closure
      // needed by a dynamically linked worker. General host executables,
      // /usr/local, service data and credential roots are deliberately absent.
      "--tmpfs", "/",
      "--dir", "/usr",
      "--ro-bind-try", "/usr/lib", "/usr/lib",
      "--ro-bind-try", "/usr/lib64", "/usr/lib64",
      "--dir", "/usr/share",
      "--ro-bind-try", "/usr/share/fonts", "/usr/share/fonts",
      "--ro-bind-try", "/usr/share/fontconfig", "/usr/share/fontconfig",
      "--symlink", "usr/lib", "/lib",
      "--symlink", "usr/lib64", "/lib64",
      "--dir", "/etc",
      "--ro-bind-try", "/etc/ld.so.cache", "/etc/ld.so.cache",
      "--ro-bind-try", "/etc/fonts", "/etc/fonts",
      "--ro-bind-try", "/etc/ssl", "/etc/ssl",
      "--dir", "/var",
      "--dir", "/var/cache",
      "--ro-bind-try", "/var/cache/fontconfig", "/var/cache/fontconfig",
      "--tmpfs", "/home",
      "--tmpfs", "/root",
      "--tmpfs", "/run",
      "--tmpfs", "/tmp",
      "--proc", "/proc",
      "--dev", "/dev",
      "--bind", profileDir, "/hepta-profile",
      "--ro-bind", workerPath, "/hepta-worker",
      "--chdir", "/hepta-profile",
      "--setenv", "HOME", "/hepta-profile",
      "--setenv", "TMPDIR", "/tmp",
      "--setenv", "HEPTA_BROWSER_WORKER_PROTOCOL", "1",
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

export class SubprocessBrowserDriver {
  #workerPath;
  #workerDigest;
  #profileRoot;
  #launcher;
  #child = null;
  #client = null;
  #profileDir = null;
  #verifiedWorkerPath = null;
  #sessionId = null;
  #generation = null;
  #processId = null;
  #process = null;
  #starting = false;
  #stopping = false;
  #retirementStarted = false;
  #retiredProfiles = new Map();

  constructor({ workerPath, workerDigest, profileRoot, launcher }) {
    if (!isAbsolute(workerPath)) throw new TypeError("workerPath must be absolute");
    if (!isAbsolute(profileRoot)) throw new TypeError("profileRoot must be absolute");
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
      if (posture[key] !== true) throw new TypeError(`launcher posture does not enforce ${key}`);
    }
    if (typeof launcher.spawn !== "function") throw new TypeError("launcher.spawn must be a function");
    this.#workerPath = workerPath;
    this.#workerDigest = expectedDigest(workerDigest, "workerDigest");
    this.#profileRoot = profileRoot;
    this.#launcher = launcher;
  }

  async start(input, { signal } = {}) {
    if (this.#starting || this.#child || this.#profileDir) {
      throw new TypeError("browser worker is already started or cleanup remains owned");
    }
    if (signal?.aborted) throw new Error("browser worker startup cancelled");
    // Snapshot and validate the complete input before any asynchronous file I/O.
    const frame = buildWorkerFrame({ sessionId: input.profileId, generation: input.generation,
      sequence: 1, kind: "start", requestId: "browser.start.preflight", payload: input });
    encodeWorkerFrame(frame);
    const request = frame.payload;
    const retired = this.#retiredProfiles.get(request.profileId);
    if (!retired && this.#retiredProfiles.size >= 1024) {
      throw new TypeError("browser worker retained-profile capacity exhausted");
    }
    if (retired && request.generation <= retired.generation) {
      throw new TypeError("browser worker generation was already retired");
    }
    this.#starting = true;
    this.#sessionId = request.profileId;
    this.#generation = request.generation;
    try {
      const verifiedWorkerBytes = await this.#readVerifiedWorkerArtifact();
      if (signal?.aborted) throw new Error("browser worker startup cancelled");
      await mkdir(this.#profileRoot, { recursive: true, mode: 0o700 });
      this.#profileDir = join(this.#profileRoot, `${request.profileId}.${request.generation}.${randomUUID()}`);
      await mkdir(this.#profileDir, { mode: 0o700 });
      this.#verifiedWorkerPath = join(this.#profileDir, ".verified-worker");
      await this.#writePrivateVerifiedWorker(verifiedWorkerBytes);
      if (signal?.aborted) throw new Error("browser worker startup cancelled");
      this.#child = this.#launcher.spawn({ workerPath: this.#verifiedWorkerPath,
        profileDir: this.#profileDir });
      this.#process = new OwnedWorkerProcess(this.#child);
      if (!this.#child.stdin || !this.#child.stdout) {
        throw new TypeError("launcher did not return a pipe-connected child process");
      }
      this.#processId = `servo.pid.${this.#child.pid}`;
      this.#client = new PrivateWorkerClient({ child: this.#child,
        sessionId: this.#sessionId, generation: this.#generation });
      const observed = await this.#client.request("start",
        `${request.profileId}.${request.generation}`, request, { signal });
      if (signal?.aborted) throw new Error("browser worker startup cancelled before delivery");
      if (observed.started !== true) throw new TypeError("worker did not acknowledge start");
      return { started: true, processId: this.#processId };
    } catch (error) {
      this.#retirementStarted = true;
      try { await this.#retire({ signal }); }
      catch (cause) {
        throw new AggregateError([error, cause], "browser startup failed; cleanup remains owned");
      }
      throw error;
    } finally { this.#starting = false; }
  }

  async observe(input, { signal } = {}) {
    this.#requireSession(input);
    return this.#client.request("observe", `page.${input.profileId}`, input, { signal });
  }

  async dispatch(input, { signal } = {}) {
    this.#requireSession(input);
    let crossed = false;
    let resolveBoundary;
    const boundary = new Promise((resolve) => { resolveBoundary = resolve; });
    const response = this.#client.request("dispatch", input.operationId, input, {
      signal,
      onDispatched: () => {
        if (crossed) return;
        crossed = true;
        resolveBoundary();
      },
    });
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
    return this.#client.request("reconcile", input.operationId, input, { signal });
  }

  async stop(input, { signal } = {}) {
    const generation = input.generation ?? input.profileGeneration;
    const retired = this.#retiredProfiles.get(input.profileId);
    if (retired && generation === retired.generation) {
      if (input.processId !== undefined && input.processId !== retired.processId) {
        throw new TypeError("browser worker historical process identity mismatch");
      }
      return { ...retired.observation };
    }
    if (this.#starting || this.#stopping) throw new Error("browser worker lifecycle change in progress");
    this.#requireIdentity(input);
    if (!this.#child && !this.#profileDir) throw new TypeError("browser worker is not started");
    this.#stopping = true;
    try {
      if (!this.#retirementStarted) {
        this.#retirementStarted = true;
        // A stop response is only a protocol acknowledgment. Bound that wait,
        // then require actual child exit and stdio closure even if it rejects.
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 1000);
        try {
          await this.#client?.request("stop", `${input.profileId}.${generation}`, input,
            { signal: signal ? AbortSignal.any([signal, controller.signal]) : controller.signal });
        } catch { /* the durable effect owner still retains unknown operations */ }
        finally { clearTimeout(timer); }
      }
      return await this.#retire({ signal });
    } finally { this.#stopping = false; }
  }

  async #retire({ signal } = {}) {
    this.#client?.close();
    if (this.#child) {
      if (!this.#process) throw new Error("browser worker lacks observable cleanup; ownership retained");
      await this.#process.retire({ signal });
    }
    // Preserve both handle and profile if file cleanup fails. Re-entry never
    // resends stop or another effect and cannot start a replacement process.
    await this.#cleanupProfile();
    const observation = { stopped: true, ...(this.#process?.observation ?? {
      directChildExited: false, stdioClosed: false, spawnFailed: false,
    }), descendantExitVerified: false };
    if (this.#child) {
      this.#retiredProfiles.set(this.#sessionId, { generation: this.#generation,
        processId: this.#processId, observation });
    }
    this.#child = null;
    this.#client = null;
    this.#process = null;
    this.#processId = null;
    this.#retirementStarted = false;
    return { ...observation };
  }

  async #readVerifiedWorkerArtifact() {
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const handle = await open(this.#workerPath, constants.O_RDONLY | noFollow);
    try {
      const info = await handle.stat();
      if (!info.isFile() || info.size < 1 || info.size > MAX_WORKER_ARTIFACT_BYTES) {
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

  async #writePrivateVerifiedWorker(bytes) {
    const noFollow = constants.O_NOFOLLOW ?? 0;
    const flags = constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | noFollow;
    const handle = await open(this.#verifiedWorkerPath, flags, 0o500);
    try {
      await handle.writeFile(bytes);
      await handle.sync();
      const info = await handle.stat();
      if (!info.isFile() || info.size !== bytes.length) {
        throw new TypeError("verified browser worker copy is not a regular exact-length file");
      }
    } finally {
      await handle.close();
    }
  }

  #requireSession(input) {
    if (this.#starting || this.#retirementStarted || !this.#child || !this.#client) {
      throw new TypeError("browser worker is not started or is retiring");
    }
    this.#requireIdentity(input);
  }

  #requireIdentity(input) {
    const generation = input.generation ?? input.profileGeneration;
    if (input.profileId !== this.#sessionId || generation !== this.#generation) {
      throw new TypeError("browser worker session or generation mismatch");
    }
    if (input.processId !== undefined && input.processId !== this.#processId) {
      throw new TypeError("browser worker process identity mismatch");
    }
  }

  async #cleanupProfile() {
    if (!this.#profileDir) return;
    const profileDir = this.#profileDir;
    await rm(profileDir, { recursive: true, force: true });
    this.#profileDir = null;
    this.#verifiedWorkerPath = null;
  }
}

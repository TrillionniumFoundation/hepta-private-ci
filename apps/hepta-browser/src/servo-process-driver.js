import { createHash, randomBytes } from "node:crypto";
import { createReadStream } from "node:fs";
import { access, chmod, lstat, mkdir, realpath } from "node:fs/promises";
import { isAbsolute, resolve } from "node:path";
import { spawn } from "node:child_process";

const DIGEST = /^[0-9a-f]{64}$/;
const MAX_FRAME_BYTES = 1024 * 1024;
const MAX_PENDING = 64;

function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

function requireDigest(value, name) {
  if (typeof value !== "string" || !DIGEST.test(value) || /^0+$/.test(value)) {
    throw new TypeError(`${name} must be a non-zero lowercase SHA-256 digest`);
  }
  return value;
}

function absolutePath(value, name) {
  if (typeof value !== "string" || !isAbsolute(value)) {
    throw new TypeError(`${name} must be an absolute path`);
  }
  return resolve(value);
}

async function sha256File(path) {
  const hash = createHash("sha256");
  await new Promise((resolvePromise, reject) => {
    const stream = createReadStream(path);
    stream.on("data", (chunk) => hash.update(chunk));
    stream.on("end", resolvePromise);
    stream.on("error", reject);
  });
  return hash.digest("hex");
}


async function requireRealRegularFile(path, name) {
  const metadata = await lstat(path);
  if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.nlink !== 1) {
    throw new TypeError(`${name} must be one regular non-symlink file`);
  }
  if ((await realpath(path)) !== path) {
    throw new TypeError(`${name} must not traverse symlink components`);
  }
}

async function requireRealDirectory(path, name) {
  const metadata = await lstat(path);
  if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
    throw new TypeError(`${name} must be a non-symlink directory`);
  }
  if ((await realpath(path)) !== path) {
    throw new TypeError(`${name} must not traverse symlink components`);
  }
}

function canonicalDigest(value) {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

export class LinuxBubblewrapSandbox {
  #bwrapPath;
  #bwrapDigest;
  #workerPath;
  #workerDigest;
  #profileRoot;

  constructor({
    bwrapPath,
    bwrapDigest,
    workerPath,
    workerDigest,
    profileRoot,
  }) {
    if (process.platform !== "linux") {
      throw new TypeError("LinuxBubblewrapSandbox is available only on Linux");
    }
    this.#bwrapPath = absolutePath(bwrapPath, "bwrapPath");
    this.#bwrapDigest = requireDigest(bwrapDigest, "bwrapDigest");
    this.#workerPath = absolutePath(workerPath, "workerPath");
    this.#workerDigest = requireDigest(workerDigest, "workerDigest");
    this.#profileRoot = absolutePath(profileRoot, "profileRoot");
  }

  async prepare({ profileId, generation }) {
    await requireRealRegularFile(this.#bwrapPath, "bwrapPath");
    await requireRealRegularFile(this.#workerPath, "workerPath");
    await requireRealDirectory(this.#profileRoot, "profileRoot");
    if (typeof profileId !== "string" || !/^[A-Za-z0-9._:-]{1,128}$/.test(profileId)) {
      throw new TypeError("profileId must be a bounded stable identifier");
    }
    if (!Number.isSafeInteger(generation) || generation < 1) {
      throw new TypeError("generation must be a positive safe integer");
    }
    const profileDir = resolve(this.#profileRoot, `${profileId}.${generation}`);
    if (!profileDir.startsWith(`${this.#profileRoot}/`)) {
      throw new TypeError("profile directory escaped the browser profile root");
    }
    await mkdir(profileDir, { recursive: false, mode: 0o700 }).catch((error) => {
      if (error?.code !== "EEXIST") throw error;
    });
    await requireRealDirectory(profileDir, "profile directory");
    await chmod(profileDir, 0o700);
    const workerInside = "/worker/hepta-servo-worker";
    const args = [
      "--die-with-parent",
      "--new-session",
      "--unshare-pid",
      "--unshare-net",
      "--unshare-ipc",
      "--unshare-uts",
      "--clearenv",
      "--setenv",
      "HOME",
      "/profile",
      "--setenv",
      "TMPDIR",
      "/tmp",
      "--proc",
      "/proc",
      "--dev",
      "/dev",
      "--tmpfs",
      "/tmp",
      "--dir",
      "/worker",
      "--ro-bind",
      this.#workerPath,
      workerInside,
      "--ro-bind",
      "/usr",
      "/usr",
      "--ro-bind-try",
      "/lib",
      "/lib",
      "--ro-bind-try",
      "/lib64",
      "/lib64",
      "--bind",
      profileDir,
      "/profile",
      "--chdir",
      "/profile",
      "--",
      workerInside,
      "--control-fd",
      "3",
    ];
    const policy = Object.freeze({
      externalNetwork: "denied_by_network_namespace",
      controlTransport: "inherited_fd_3",
      profileMount: "private_rw_bind",
      rootFilesystem: "minimal_read_only_system_bindings",
      workerPath: this.#workerPath,
      workerDigest: this.#workerDigest,
      launcherPath: this.#bwrapPath,
      launcherDigest: this.#bwrapDigest,
    });
    return Object.freeze({
      command: this.#bwrapPath,
      args: Object.freeze(args),
      env: Object.freeze({}),
      verifications: Object.freeze([
        Object.freeze({ path: this.#bwrapPath, sha256: this.#bwrapDigest }),
        Object.freeze({ path: this.#workerPath, sha256: this.#workerDigest }),
      ]),
      isolation: Object.freeze({
        processIsolationEnforced: true,
        profileIsolationEnforced: true,
        credentialIsolationEnforced: true,
        networkPolicyEnforced: true,
        sandboxDigest: canonicalDigest({ args, policy }),
        networkPolicyDigest: canonicalDigest({ externalNetwork: policy.externalNetwork }),
      }),
    });
  }
}

class FramedChannel {
  #stream;
  #buffer = Buffer.alloc(0);
  #pending = new Map();
  #closed = false;

  constructor(stream) {
    if (!stream || typeof stream.write !== "function" || typeof stream.on !== "function") {
      throw new TypeError("worker control fd must be a duplex stream");
    }
    this.#stream = stream;
    stream.on("data", (chunk) => this.#ingest(chunk));
    stream.on("error", (error) => this.#close(error));
    stream.on("close", () => this.#close(new Error("worker control channel closed")));
  }

  request(message, { signal } = {}) {
    if (this.#closed) {
      return Promise.reject(new Error("worker control channel is closed"));
    }
    if (this.#pending.size >= MAX_PENDING) {
      return Promise.reject(new Error("worker control channel capacity is exhausted"));
    }
    const requestId = message.requestId;
    if (this.#pending.has(requestId)) {
      return Promise.reject(new Error("duplicate worker request id"));
    }
    const encoded = Buffer.from(JSON.stringify(message), "utf8");
    if (encoded.byteLength > MAX_FRAME_BYTES) {
      return Promise.reject(new TypeError("worker request exceeds the frame byte limit"));
    }
    const frame = Buffer.allocUnsafe(4 + encoded.byteLength);
    frame.writeUInt32BE(encoded.byteLength, 0);
    encoded.copy(frame, 4);
    return new Promise((resolvePromise, reject) => {
      const abort = () => {
        this.#pending.delete(requestId);
        reject(signal.reason ?? new Error("worker request aborted"));
      };
      if (signal?.aborted) {
        abort();
        return;
      }
      signal?.addEventListener("abort", abort, { once: true });
      this.#pending.set(requestId, {
        resolve: resolvePromise,
        reject,
        cleanup: () => signal?.removeEventListener("abort", abort),
      });
      this.#stream.write(frame, (error) => {
        if (error) {
          const pending = this.#pending.get(requestId);
          if (pending) {
            this.#pending.delete(requestId);
            pending.cleanup();
            pending.reject(error);
          }
        }
      });
    });
  }

  #ingest(chunk) {
    this.#buffer = Buffer.concat([this.#buffer, chunk]);
    while (this.#buffer.byteLength >= 4) {
      const length = this.#buffer.readUInt32BE(0);
      if (length === 0 || length > MAX_FRAME_BYTES) {
        this.#close(new TypeError("worker response has an invalid frame length"));
        return;
      }
      if (this.#buffer.byteLength < 4 + length) return;
      const payload = this.#buffer.subarray(4, 4 + length);
      this.#buffer = this.#buffer.subarray(4 + length);
      let message;
      try {
        message = JSON.parse(payload.toString("utf8"));
      } catch {
        this.#close(new TypeError("worker response is not valid JSON"));
        return;
      }
      const pending = this.#pending.get(message.requestId);
      if (!pending) continue;
      this.#pending.delete(message.requestId);
      pending.cleanup();
      if (message.ok !== true) {
        pending.reject(new Error("worker rejected browser request"));
      } else {
        pending.resolve(message.result);
      }
    }
  }

  #close(error) {
    if (this.#closed) return;
    this.#closed = true;
    for (const pending of this.#pending.values()) {
      pending.cleanup();
      pending.reject(error);
    }
    this.#pending.clear();
  }
}

export class ServoProcessDriver {
  supportsAbort = true;
  #sandbox;
  #spawn;
  #sessions = new Map();

  constructor({ sandbox, spawnImpl = spawn }) {
    if (!sandbox || typeof sandbox.prepare !== "function") {
      throw new TypeError("sandbox.prepare must be a function");
    }
    if (typeof spawnImpl !== "function") {
      throw new TypeError("spawnImpl must be a function");
    }
    this.#sandbox = sandbox;
    this.#spawn = spawnImpl;
  }

  async start(payload, { signal } = {}) {
    const spec = await this.#sandbox.prepare(payload);
    for (const verification of spec.verifications ?? []) {
      await access(verification.path);
      const actual = await sha256File(verification.path);
      if (actual !== verification.sha256) {
        throw new TypeError(`browser worker artifact digest mismatch: ${verification.path}`);
      }
    }
    const child = this.#spawn(spec.command, [...spec.args], {
      env: { ...spec.env },
      stdio: ["ignore", "ignore", "pipe", "pipe"],
      windowsHide: true,
    });
    if (!child.stdio?.[3]) {
      child.kill?.("SIGKILL");
      throw new TypeError("browser worker did not expose inherited control fd 3");
    }
    const channel = new FramedChannel(child.stdio[3]);
    const session = {
      child,
      channel,
      sequence: 0,
      profileId: payload.profileId,
      generation: payload.generation,
      processId: `servo.pid.${child.pid}`,
      isolation: spec.isolation,
    };
    this.#sessions.set(payload.profileId, session);
    try {
      const result = requireRecord(
        await this.#request(session, "start", payload, signal),
        "worker start result",
      );
      if (result.started !== true) {
        throw new TypeError("browser worker did not acknowledge startup");
      }
      return {
        started: true,
        processId: session.processId,
        isolation: session.isolation,
      };
    } catch (error) {
      this.#sessions.delete(payload.profileId);
      child.kill?.("SIGKILL");
      throw error;
    }
  }

  observe(payload, { signal } = {}) {
    return this.#sessionRequest(payload, "observe", signal);
  }

  act(payload, { signal } = {}) {
    return this.#sessionRequest(payload, "act", signal);
  }

  reconcile(payload, { signal } = {}) {
    return this.#sessionRequest(payload, "reconcile", signal);
  }

  async contain(payload) {
    const session = this.#sessions.get(payload.profileId);
    if (!session) return { contained: true };
    session.child.kill?.("SIGKILL");
    this.#sessions.delete(payload.profileId);
    return { contained: true };
  }

  async stop(payload, { signal } = {}) {
    const session = this.#sessions.get(payload.profileId);
    if (!session) return { stopped: true };
    try {
      await this.#request(session, "stop", payload, signal);
    } finally {
      session.child.kill?.("SIGTERM");
      this.#sessions.delete(payload.profileId);
    }
    return { stopped: true };
  }

  async #sessionRequest(payload, type, signal) {
    const session = this.#sessions.get(payload.profileId);
    if (!session) {
      throw new TypeError("browser worker session is not running");
    }
    return requireRecord(
      await this.#request(session, type, payload, signal),
      `worker ${type} result`,
    );
  }

  #request(session, type, payload, signal) {
    session.sequence += 1;
    const requestId = randomBytes(16).toString("hex");
    return session.channel.request(
      {
        protocol: "hepta.browser.worker.v1",
        type,
        requestId,
        sequence: session.sequence,
        profileId: session.profileId,
        generation: session.generation,
        payload,
      },
      { signal },
    );
  }
}

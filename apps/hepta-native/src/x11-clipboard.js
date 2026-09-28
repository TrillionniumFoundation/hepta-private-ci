/** Bounded Linux/X11 clipboard adapter for the existing native platform port.
 *
 * The host supplies immutable content-addressed resources, a pinned executable,
 * the clock used by NativeShellRuntime, and the existing final-use authorizer.
 * No authority, persistent effect history, ambient display or shell is invented.
 */
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { closeSync, constants, fstatSync, openSync, readSync } from "node:fs";
import { isAbsolute } from "node:path";
import { nativePlatformPayloadDigestV1 } from "./computer-action.js";

const MAX_TEXT = 65_536;
const MAX_EXECUTABLE = 4 * 1024 * 1024;
const MAX_WRITERS = 4;
const ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^(?!0{64}$)[0-9a-f]{64}$/;
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// A stop request is not evidence of process exit. Keep the owner's child entry
// until close and bound graceful/forced termination even after the action expires.
function stopChild(child) {
  if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve(true);
  return new Promise((resolve) => {
    let done = false;
    const finish = (stopped) => {
      if (done) return;
      done = true;
      clearTimeout(killTimer); clearTimeout(deadlineTimer);
      child.removeListener("close", closed);
      resolve(stopped);
    };
    const closed = () => finish(true);
    const killTimer = setTimeout(() => child.kill("SIGKILL"), 500);
    const deadlineTimer = setTimeout(() => finish(false), 1000);
    child.once("close", closed);
    child.kill("SIGTERM");
  });
}

export function clipboardTextReference(text) {
  if (typeof text !== "string" || text.includes("\0") ||
      Buffer.byteLength(text, "utf8") > MAX_TEXT || text.length === 0 ||
      Buffer.from(text, "utf8").toString("utf8") !== text) {
    throw new TypeError("clipboard text must be bounded exact UTF-8");
  }
  return `text.sha256:${sha256(Buffer.from(text, "utf8"))}`;
}

function ownFields(input, expected) {
  if (!input || typeof input !== "object" ||
      ![null, Object.prototype].includes(Object.getPrototypeOf(input))) {
    throw new TypeError("clipboard request must be a plain record");
  }
  const fields = Object.getOwnPropertyDescriptors(input);
  if (Reflect.ownKeys(fields).length !== expected.length ||
      expected.some((key) => !fields[key]?.enumerable || !Object.hasOwn(fields[key], "value"))) {
    throw new TypeError("clipboard request requires exact own data fields");
  }
  return Object.freeze(Object.fromEntries(expected.map((key) => [key, fields[key].value])));
}

export class X11ClipboardPlatform {
  #resources = new Map();
  #executable; #executableDigest; #display; #clock; #finalUse;
  #writers = new Set();
  #observers = new Set();
  #closed = false;

  constructor({ executablePath, executableSha256, display, resources, monotonicMicros, finalUse }) {
    if (process.platform !== "linux" || !isAbsolute(executablePath) ||
        !DIGEST.test(executableSha256) || !/^:[0-9]{1,5}$/.test(display) ||
        typeof monotonicMicros !== "function" ||
        !finalUse || typeof finalUse.withVerifiedUse !== "function" ||
        !Array.isArray(resources) || resources.length > 16) {
      throw new TypeError("invalid explicit Linux/X11 clipboard host profile");
    }
    for (const raw of resources) {
      const value = ownFields(raw, ["resource", "text"]);
      if (value.resource !== clipboardTextReference(value.text) || this.#resources.has(value.resource)) {
        throw new TypeError("clipboard resource is not a unique content-addressed reference");
      }
      this.#resources.set(value.resource, Buffer.from(value.text, "utf8"));
    }
    this.#executable = executablePath;
    this.#executableDigest = executableSha256;
    this.#display = display;
    this.#clock = monotonicMicros;
    this.#finalUse = finalUse;
  }

  permission(input) {
    const allowed = !this.#closed && input.action === "copy_text" && this.#resources.has(input.resource);
    // Availability only. This value is not a capability or final-use witness.
    return Object.freeze({ allowed, outcomeDigest: sha256(Buffer.from(`clipboard-available:${allowed}`)) });
  }

  #now() {
    const now = this.#clock();
    if (!Number.isSafeInteger(now) || now < 0) throw new TypeError("invalid clipboard clock");
    return now;
  }

  #start(args) {
    const fd = openSync(this.#executable, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    try {
      const stat = fstatSync(fd);
      if (!stat.isFile() || stat.size < 1 || stat.size > MAX_EXECUTABLE) {
        throw new TypeError("clipboard executable identity mismatch");
      }
      const bytes = Buffer.alloc(stat.size + 1);
      let size = 0, count = 0;
      while (size < bytes.length && (count = readSync(fd, bytes, size, bytes.length - size, null)) > 0) size += count;
      const after = fstatSync(fd);
      if (size !== stat.size || after.size !== stat.size || after.mtimeMs !== stat.mtimeMs ||
          sha256(bytes.subarray(0, size)) !== this.#executableDigest) {
        throw new TypeError("clipboard executable identity mismatch");
      }
      // Linux descriptor execution prevents a path replacement between checking
      // the executable and exec. Shared libraries/X server remain host assumptions.
      const child = spawn("/proc/self/fd/3", [...args, "-display", this.#display], {
        shell: false, env: { DISPLAY: this.#display, LANG: "C.UTF-8", LC_ALL: "C.UTF-8" },
        stdio: ["pipe", "pipe", "pipe", fd], detached: false,
      });
      child.on("error", () => {});
      child.stdin.on("error", () => {});
      return child;
    } finally {
      closeSync(fd);
    }
  }

  #observe(deadline) {
    return new Promise((resolve) => {
      const remaining = deadline - this.#now();
      if (remaining <= 0 || this.#closed || this.#observers.size >= MAX_WRITERS) return resolve(null);
      const child = this.#start(["-selection", "clipboard", "-out"]);
      this.#observers.add(child);
      child.once("close", () => this.#observers.delete(child));
      const chunks = [];
      let size = 0, errorBytes = 0, done = false;
      const finish = async (value) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        const stopped = await stopChild(child);
        resolve(stopped ? value : null);
      };
      const timer = setTimeout(() => finish(null), Math.max(1, Math.min(500, Math.ceil(remaining / 1000))));
      child.stdout.on("data", (chunk) => {
        size += chunk.length;
        if (size > MAX_TEXT) return finish(null);
        chunks.push(chunk);
      });
      child.stderr.on("data", (chunk) => { errorBytes += chunk.length; if (errorBytes > 4096) finish(null); });
      child.on("error", () => finish(null));
      child.on("close", (code) => finish(code === 0 ? Buffer.concat(chunks) : null));
      child.stdin.end();
    });
  }

  async invoke(input) {
    const request = ownFields(input, ["sessionId", "sessionGeneration", "operationId", "action", "resource",
      "finalPayloadDigest", "sourceActionDigest", "deadlineMonotonicMicros"]);
    if (this.#closed || request.action !== "copy_text" || !this.#resources.has(request.resource) ||
        typeof request.operationId !== "string" || !ID.test(request.operationId) ||
        typeof request.sessionId !== "string" || !ID.test(request.sessionId) ||
        !Number.isSafeInteger(request.sessionGeneration) || request.sessionGeneration < 1 ||
        typeof request.sourceActionDigest !== "string" || !DIGEST.test(request.sourceActionDigest) ||
        request.finalPayloadDigest !== nativePlatformPayloadDigestV1("copy_text", request.resource) ||
        !Number.isSafeInteger(request.deadlineMonotonicMicros) ||
        request.deadlineMonotonicMicros <= this.#now() || this.#writers.size >= MAX_WRITERS) {
      throw new TypeError("clipboard invocation is not currently admissible");
    }
    const text = this.#resources.get(request.resource);
    let writer = null, gateOpen = true, dispatchEntered = false, writerFailed = false;
    try {
      const response = this.#finalUse.withVerifiedUse(request, () => {
        if (!gateOpen || dispatchEntered || this.#closed || request.deadlineMonotonicMicros <= this.#now()) {
          throw new TypeError("clipboard final-use dispatch is closed");
        }
        dispatchEntered = true;
        writer = this.#start(["-selection", "clipboard", "-in", "-quiet", "-loops", "0"]);
        this.#writers.add(writer);
        writer.on("error", () => { writerFailed = true; });
        writer.on("close", () => { writerFailed = true; this.#writers.delete(writer); });
        writer.stdout.resume(); writer.stderr.resume();
        writer.stdin.end(text);
      });
      if (response && typeof response.then === "function") {
        void Promise.resolve(response).catch(() => {});
        throw new TypeError("clipboard profile requires synchronous final-use authorization");
      }
      if (writer === null) throw new TypeError("clipboard final-use dispatch was not authorized");
    } finally {
      gateOpen = false;
    }
    // Observation retries only: exactly one clipboard writer was dispatched.
    for (let attempt = 0; attempt < 20 && !writerFailed && !this.#closed; ++attempt) {
      if (request.deadlineMonotonicMicros <= this.#now()) break;
      const observed = await this.#observe(request.deadlineMonotonicMicros);
      if (observed?.equals(text) && !writerFailed && request.deadlineMonotonicMicros > this.#now()) {
        const outcome = ["hepta.x11-clipboard-outcome.v1", request.operationId, request.sourceActionDigest,
          request.finalPayloadDigest, this.#display, this.#executableDigest, sha256(observed)];
        return Object.freeze({ terminalObserved: true, status: "succeeded",
          outcomeDigest: sha256(Buffer.from(JSON.stringify(outcome))) });
      }
      await delay(10);
    }
    return Object.freeze({ terminalObserved: false, status: "indeterminate", outcomeDigest: null });
  }

  async close() {
    this.#closed = true;
    const writers = [...this.#writers], observers = [...this.#observers];
    const [writerStops, observerStops] = await Promise.all([
      Promise.all(writers.map(stopChild)), Promise.all(observers.map(stopChild)),
    ]);
    return Object.freeze({ stopped: writerStops.every(Boolean) && observerStops.every(Boolean),
      unresolvedWriters: writerStops.filter((value) => !value).length,
      unresolvedObservers: observerStops.filter((value) => !value).length });
  }
}

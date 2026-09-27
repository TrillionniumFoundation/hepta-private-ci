import { ChildProcess } from "node:child_process";
import { readFile, readdir } from "node:fs/promises";
import { performance } from "node:perf_hooks";

const MAX_OBSERVED_PROCESSES = 4096;
const MAX_WAIT_MS = 120_000;
const POLL_MS = 10;

function containmentError(message, cause) {
  const error = new Error(message, cause === undefined ? undefined : { cause });
  error.name = "BrowserContainmentError";
  error.code = "BROWSER_CONTAINMENT_UNPROVED";
  return error;
}

async function processIdentity(pid) {
  try {
    const text = await readFile(`/proc/${pid}/stat`, "utf8");
    const end = text.lastIndexOf(") ");
    const fields = text.slice(end + 2).trim().split(/\s+/);
    if (end < 0 || !/^\d+$/.test(fields[19] ?? "")) {
      throw containmentError("worker process identity is malformed");
    }
    return { pid, startTime: fields[19] };
  } catch (error) {
    if (error?.code === "ENOENT" || error?.code === "ESRCH") return null;
    throw error;
  }
}

async function processChildren(identity) {
  const result = new Set();
  let tasks;
  try {
    tasks = await readdir(`/proc/${identity.pid}/task`);
  } catch (error) {
    if (error?.code === "ENOENT" || error?.code === "ESRCH") return [];
    throw error;
  }
  if (tasks.length > MAX_OBSERVED_PROCESSES) {
    throw containmentError("worker task census exceeds its bound");
  }
  for (const task of tasks) {
    try {
      const children = await readFile(`/proc/${identity.pid}/task/${task}/children`, "utf8");
      for (const token of children.trim().split(/\s+/).filter(Boolean)) {
        const pid = Number(token);
        if (!Number.isSafeInteger(pid) || pid < 1) {
          throw containmentError("worker descendant identity is malformed");
        }
        result.add(pid);
      }
    } catch (error) {
      if (error?.code !== "ENOENT" && error?.code !== "ESRCH") throw error;
    }
  }
  // Do not attach a reused PID's children to the original process lifetime.
  const current = await processIdentity(identity.pid);
  return current?.startTime === identity.startTime ? [...result] : [];
}

/**
 * Retains the actual ChildProcess and observed Linux process lifetimes until
 * exit. A signal request is never an exit receipt. Descendants are observed,
 * not signalled by raw PID; the production launcher owns namespace teardown.
 * A census is not independent proof that the target sandbox is qualified.
 */
export class OwnedBrowserChild {
  #child;
  #closed = false;
  #exited = false;
  #spawnFailed = false;
  #observed = new Map();
  #rootIdentity = null;
  #capture;
  #termination = null;

  constructor(child) {
    if (!child || typeof child.once !== "function" || typeof child.kill !== "function") {
      throw new TypeError("worker ownership requires a ChildProcess");
    }
    this.#child = child;
    child.once("exit", () => { this.#exited = true; });
    child.once("close", () => { this.#closed = true; this.#exited = true; });
    child.on("error", () => {
      // Spawn failure has no acquired PID. Later errors are not exit evidence.
      if (!Number.isSafeInteger(child.pid) || child.pid < 1) this.#spawnFailed = true;
    });
    this.#capture = this.#captureTree();
    // Capture failures are rethrown by terminate; avoid an unhandled rejection
    // while the live owner is still starting or servicing the worker.
    this.#capture.catch(() => {});
  }

  get closed() { return this.#closed; }
  get exited() { return this.#exited; }

  async #captureTree() {
    if (process.platform !== "linux" || !(this.#child instanceof ChildProcess) ||
        !Number.isSafeInteger(this.#child.pid)) return;
    const root = await processIdentity(this.#child.pid);
    if (root === null) return;
    if (this.#rootIdentity !== null && root.startTime !== this.#rootIdentity.startTime) return;
    this.#rootIdentity ??= root;
    const pending = [root.pid];
    const seen = new Set();
    while (pending.length) {
      const pid = pending.pop();
      if (seen.has(pid)) continue;
      seen.add(pid);
      if (seen.size > MAX_OBSERVED_PROCESSES) {
        throw containmentError("worker descendant census exceeds its bound");
      }
      const identity = await processIdentity(pid);
      if (identity === null) continue;
      this.#observed.set(`${identity.pid}:${identity.startTime}`, identity);
      pending.push(...await processChildren(identity));
    }
  }

  async terminate({ timeoutMs = 10_000 } = {}) {
    if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > MAX_WAIT_MS) {
      throw new TypeError("worker termination timeout is outside the hard bound");
    }
    if (this.#termination !== null) return this.#termination;
    this.#termination = this.#terminate(timeoutMs);
    try {
      return await this.#termination;
    } finally {
      // Retrying must inspect retained handles/identities, never a replacement.
      this.#termination = null;
    }
  }

  async #terminate(timeoutMs) {
    const deadline = performance.now() + timeoutMs;
    let captureError = null;
    try {
      await this.#capture;
      if (!this.#exited) await this.#captureTree();
    } catch (error) {
      captureError = error;
    }
    let signalError = null;
    if (!this.#exited && !this.#spawnFailed &&
        this.#child.exitCode == null && this.#child.signalCode == null) {
      try {
        this.#child.kill("SIGKILL");
      } catch (error) {
        signalError = error;
      }
    }
    while (true) {
      let observedGone = true;
      for (const identity of this.#observed.values()) {
        const current = await processIdentity(identity.pid);
        if (current?.startTime === identity.startTime) observedGone = false;
      }
      if (this.#exited && observedGone) {
        if (captureError !== null) {
          throw containmentError("worker exited but descendant observation failed", captureError);
        }
        this.#child.stdin?.destroy();
        this.#child.stdout?.destroy();
        this.#child.stderr?.destroy();
        return Object.freeze({
          processExitObserved: true,
          observedDescendantsExited: true,
          observedProcessCount: this.#observed.size,
        });
      }
      if (performance.now() >= deadline) {
        throw containmentError("worker termination is not yet observed; ownership retained", signalError);
      }
      await new Promise(resolve => setTimeout(resolve, POLL_MS));
    }
  }
}

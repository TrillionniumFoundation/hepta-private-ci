// Child-handle lifecycle only. Not a durable resource ledger or evidence that
// descendants, device allocations or external browser operations have settled.
const CLEANUP_WAIT_MS = 1000;

export class OwnedWorkerProcess {
  #child;
  #exited = false;
  #closed = false;
  #failedSpawn = false;
  #waiter = null;

  constructor(child) {
    if (!child || typeof child.on !== "function" || typeof child.kill !== "function") {
      throw new TypeError("launcher must return an observable owned child handle");
    }
    this.#child = child;
    child.on("exit", () => { this.#exited = true; this.#notify(); });
    child.on("close", () => { this.#closed = true; this.#notify(); });
    child.on("error", () => {
      // A failed signal is NOT a failed spawn. A launched PID stays owned.
      if (!Number.isInteger(child.pid) || child.pid < 1) this.#failedSpawn = true;
      this.#notify();
    });
  }

  get retired() { return this.#closed && (this.#exited || this.#failedSpawn); }

  get observation() {
    return { directChildExited: this.#exited, stdioClosed: this.#closed,
      spawnFailed: this.#failedSpawn };
  }

  async retire({ signal } = {}) {
    if (this.retired) return;
    if (this.#waiter) throw new Error("browser worker cleanup already in progress");
    if (!this.#exited && !this.#failedSpawn) {
      // Use the original ChildProcess object, never a recycled numeric PID.
      let sent;
      try { sent = this.#child.kill("SIGKILL"); }
      catch (cause) { throw new Error("browser worker cleanup signal failed; ownership retained", { cause }); }
      if (sent !== true && !this.retired) {
        throw new Error("browser worker cleanup signal denied; ownership retained");
      }
    }
    if (this.retired) return;
    if (signal?.aborted) throw new Error("browser worker cleanup cancelled; ownership retained");
    await new Promise((resolve, reject) => {
      let timer;
      const finish = (error) => {
        clearTimeout(timer);
        signal?.removeEventListener("abort", abort);
        this.#waiter = null;
        if (error) reject(error); else resolve();
      };
      const abort = () => finish(new Error("browser worker cleanup cancelled; ownership retained"));
      this.#waiter = () => finish();
      timer = setTimeout(() => finish(new Error("browser worker exit/pipe closure unobserved; ownership retained")), CLEANUP_WAIT_MS);
      signal?.addEventListener("abort", abort, { once: true });
      if (this.retired) this.#notify();
      else if (signal?.aborted) abort();
    });
  }

  #notify() { if (this.retired) this.#waiter?.(); }
}

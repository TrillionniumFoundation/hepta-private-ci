// Local maintenance only: this queue cannot admit mutations or certify a
// terminal result. ScopedRecoveryStore still verifies every removal under lock.
const fields = [
  "operationId", "semanticDigest", "method", "action", "targetId", "reason",
  "sessionId", "connectionGeneration", "generation", "displayedRevision",
  "snapshotDigest", "protocolVersion", "state", "terminalStatus",
  "auditTraceId", "outcomeDigest",
];

export class TerminalCleanupQueue {
  #complete;
  #limit;
  #batchSize;
  #deadlineMs;
  #cursor = 0;
  #pending = new Map();
  #done = new Set();
  #visible = new Set();
  #tail = Promise.resolve();

  constructor(complete, { maxEntries = 4096, batchSize = 32, deadlineMs = 5000 } = {}) {
    if (typeof complete !== "function" || !Number.isSafeInteger(maxEntries) ||
        maxEntries < 1 || maxEntries > 4096 || !Number.isSafeInteger(batchSize) ||
        batchSize < 1 || batchSize > 32 || !Number.isSafeInteger(deadlineMs) ||
        deadlineMs < 1 || deadlineMs > 5000) {
      throw new TypeError("bounded terminal cleanup requires a completion callback");
    }
    this.#complete = complete;
    this.#limit = maxEntries;
    this.#batchSize = Math.min(batchSize, maxEntries);
    this.#deadlineMs = deadlineMs;
  }

  async sync(operations, { signal } = {}) {
    if (!Array.isArray(operations) || operations.length > this.#limit) {
      throw new RangeError("terminal cleanup inventory exceeds its bound");
    }
    const selected = new Map();
    for (const operation of operations) {
      if (operation.state !== "terminal") continue;
      const snapshot = Object.freeze({ ...operation });
      const key = JSON.stringify(fields.map(field => snapshot[field]));
      selected.set(key, snapshot);
    }
    this.#visible = new Set(selected.keys());
    for (const key of this.#done) {
      if (!this.#visible.has(key)) this.#done.delete(key);
    }
    const entries = [...selected];
    const work = [...this.#pending].filter(([key]) => selected.has(key)).map(([, task]) => task);
    const deadline = new AbortController();
    const abort = () => deadline.abort(signal?.reason);
    if (signal?.aborted) abort();
    else signal?.addEventListener("abort", abort, { once: true });
    const timer = setTimeout(() => deadline.abort(new Error("terminal cleanup batch deadline")), this.#deadlineMs);
    try {
      // Rotate across the whole displayed inventory, including failed entries.
      // A slow lock cannot repeatedly starve every operation behind it.
      let scanned = 0;
      while (scanned < entries.length && this.#pending.size < this.#batchSize) {
        this.#cursor %= entries.length;
        const [key, operation] = entries[this.#cursor];
        this.#cursor = (this.#cursor + 1) % entries.length;
        scanned += 1;
        if (this.#done.has(key) || this.#pending.has(key)) continue;
        const task = this.#tail.then(async () => {
          deadline.signal.throwIfAborted();
          await this.#complete(operation, { signal: deadline.signal });
          // false means the exact record was already absent. This local memo
          // never participates in admission or runtime-success decisions.
          if (this.#visible.has(key)) this.#done.add(key);
        });
        this.#pending.set(key, task);
        this.#tail = task.then(
          () => { this.#pending.delete(key); },
          () => { this.#pending.delete(key); },
        );
        work.push(task);
      }
      const results = await Promise.allSettled(work);
      const failures = results.filter(result => result.status === "rejected");
      if (failures.length) {
        throw new AggregateError(failures.map(result => result.reason),
          "Terminal cleanup failed; failed records require recovery.");
      }
      return [...selected.keys()].every(key => this.#done.has(key));
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    }
  }

  drain() {
    return this.#tail;
  }
}

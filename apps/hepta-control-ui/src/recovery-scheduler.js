import { UI_CONTROL_ERROR_CODES as C, uiControlError } from "./errors.js";

const fatal = new Set([C.NOT_CONNECTED, C.SESSION_EXPIRED, C.SESSION_REVOKED,
  C.SESSION_IDENTITY_CHANGED, C.PERMISSION_DENIED, C.STALE_PERMISSION_REVISION, C.PROTOCOL_MISMATCH]);

export class RecoveryScheduler {
  #cursor = null;
  #running = null;
  #clock;
  #observations = 0;
  #failures = 0;
  #lastDurationMs = 0;
  #maxWaitMs = 0;
  #lastVisited = new Map();

  constructor(clock = () => Date.now()) { this.#clock = clock; }

  metrics() {
    return Object.freeze({ observations: this.#observations, failures: this.#failures,
      lastBatchDurationMs: this.#lastDurationMs, maxLookupWaitMs: this.#maxWaitMs });
  }

  run(operations, lookup, { limit = 32, concurrency = 4, signal } = {}) {
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 128 ||
        !Number.isSafeInteger(concurrency) || concurrency < 1 || concurrency > 8) {
      return Promise.reject(uiControlError(C.INVALID_INPUT, "Recovery limits are invalid."));
    }
    if (this.#running) return this.#running;
    const work = this.#run(operations, lookup, { limit, concurrency, signal });
    this.#running = work;
    work.finally(() => { if (this.#running === work) this.#running = null; }).catch(() => {});
    return work;
  }

  async #run(operations, lookup, { limit, concurrency, signal }) {
    const started = this.#clock();
    const ordered = [...operations].filter(operation => operation.state !== "submitting")
      .sort((a, b) => a.operationId < b.operationId ? -1 : a.operationId > b.operationId ? 1 : 0);
    const live = new Set(ordered.map(operation => operation.operationId));
    for (const id of this.#lastVisited.keys()) if (!live.has(id)) this.#lastVisited.delete(id);
    let start = this.#cursor === null ? 0 : ordered.findIndex(operation => operation.operationId > this.#cursor);
    if (start < 0) start = 0;
    const selected = [...ordered.slice(start), ...ordered.slice(0, start)].slice(0, limit);
    const results = new Array(selected.length);
    let index = 0;
    let failure = null;
    const worker = async () => {
      while (!failure && index < selected.length) {
        if (signal?.aborted) {
          failure = uiControlError(C.ABORTED, "Recovery batch was cancelled.", { retryable: true });
          break;
        }
        const slot = index++;
        const operation = selected[slot];
        // Advance on attempted lookup, not success, so poison entries cannot
        // monopolize the beginning of every future batch.
        this.#cursor = operation.operationId;
        const now = this.#clock();
        this.#maxWaitMs = Math.max(this.#maxWaitMs,
          Math.max(0, now - (this.#lastVisited.get(operation.operationId) ?? operation.createdAt)));
        this.#lastVisited.set(operation.operationId, now);
        try {
          results[slot] = await lookup(operation.operationId, { signal });
          this.#observations += 1;
        } catch (error) {
          this.#failures += 1;
          if (fatal.has(error?.code)) failure = error;
          else results[slot] = Object.freeze({ ...operation, recoveryError: error?.code ?? C.TRANSPORT });
        }
      }
    };
    await Promise.all(Array.from({ length: Math.min(concurrency, selected.length) }, worker));
    this.#lastDurationMs = Math.max(0, this.#clock() - started);
    if (failure) throw failure;
    return Object.freeze(results);
  }
}

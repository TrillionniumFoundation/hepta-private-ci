import { UI_CONTROL_ERROR_CODES as C, uiControlError } from "./errors.js";

const fatal = new Set([
  C.NOT_CONNECTED,
  C.SESSION_EXPIRED,
  C.SESSION_REVOKED,
  C.SESSION_IDENTITY_CHANGED,
  C.PERMISSION_DENIED,
  C.STALE_PERMISSION_REVISION,
  C.PROTOCOL_MISMATCH,
]);

const DEFAULT_INITIAL_BACKOFF_MS = 1_000;
const DEFAULT_MAX_BACKOFF_MS = 60_000;

function invalid(message) {
  return uiControlError(C.INVALID_INPUT, message);
}

export class RecoveryScheduler {
  #cursor = null;
  #running = null;
  #clock;
  #observations = 0;
  #failures = 0;
  #lastDurationMs = 0;
  #maxWaitMs = 0;
  #lastVisited = new Map();
  #backoff = new Map();
  #deferredByBackoff = 0;
  #initialBackoffMs;
  #maxBackoffMs;

  constructor(
    clock = () => Date.now(),
    {
      initialBackoffMs = DEFAULT_INITIAL_BACKOFF_MS,
      maxBackoffMs = DEFAULT_MAX_BACKOFF_MS,
    } = {},
  ) {
    if (typeof clock !== "function") {
      throw invalid("Recovery clock must be a function.");
    }
    if (
      !Number.isSafeInteger(initialBackoffMs) ||
      initialBackoffMs < 1 ||
      initialBackoffMs > 60_000 ||
      !Number.isSafeInteger(maxBackoffMs) ||
      maxBackoffMs < initialBackoffMs ||
      maxBackoffMs > 10 * 60_000
    ) {
      throw invalid("Recovery backoff limits are invalid.");
    }
    this.#clock = clock;
    this.#initialBackoffMs = initialBackoffMs;
    this.#maxBackoffMs = maxBackoffMs;
  }

  metrics() {
    let nextEligibleAt = null;
    for (const state of this.#backoff.values()) {
      if (nextEligibleAt === null || state.nextEligibleAt < nextEligibleAt) {
        nextEligibleAt = state.nextEligibleAt;
      }
    }
    return Object.freeze({
      observations: this.#observations,
      failures: this.#failures,
      lastBatchDurationMs: this.#lastDurationMs,
      maxLookupWaitMs: this.#maxWaitMs,
      deferredByBackoff: this.#deferredByBackoff,
      backoffEntries: this.#backoff.size,
      nextEligibleAt,
    });
  }

  run(operations, lookup, { limit = 32, concurrency = 4, signal } = {}) {
    if (
      !Number.isSafeInteger(limit) ||
      limit < 1 ||
      limit > 128 ||
      !Number.isSafeInteger(concurrency) ||
      concurrency < 1 ||
      concurrency > 8
    ) {
      return Promise.reject(invalid("Recovery limits are invalid."));
    }
    if (typeof lookup !== "function") {
      return Promise.reject(invalid("Recovery lookup must be a function."));
    }
    if (this.#running) return this.#running;
    const work = this.#run(operations, lookup, { limit, concurrency, signal });
    this.#running = work;
    work.finally(() => {
      if (this.#running === work) this.#running = null;
    }).catch(() => {});
    return work;
  }

  async #run(operations, lookup, { limit, concurrency, signal }) {
    const started = this.#clock();
    const ordered = [...operations]
      .filter(operation => operation.state !== "submitting")
      .sort((left, right) =>
        left.operationId < right.operationId
          ? -1
          : left.operationId > right.operationId
            ? 1
            : 0,
      );
    const live = new Set(ordered.map(operation => operation.operationId));
    for (const id of this.#lastVisited.keys()) {
      if (!live.has(id)) this.#lastVisited.delete(id);
    }
    for (const id of this.#backoff.keys()) {
      if (!live.has(id)) this.#backoff.delete(id);
    }

    let start = this.#cursor === null
      ? 0
      : ordered.findIndex(operation => operation.operationId > this.#cursor);
    if (start < 0) start = 0;
    const rotated = [...ordered.slice(start), ...ordered.slice(0, start)];
    const now = this.#clock();
    const selected = [];
    let deferred = 0;
    for (const operation of rotated) {
      const backoff = this.#backoff.get(operation.operationId);
      if (backoff && backoff.nextEligibleAt > now) {
        deferred += 1;
      } else if (selected.length < limit) {
        selected.push(operation);
      }
    }
    this.#deferredByBackoff += deferred;

    const results = new Array(selected.length);
    let index = 0;
    let failure = null;
    const worker = async () => {
      while (!failure && index < selected.length) {
        if (signal?.aborted) {
          failure = uiControlError(
            C.ABORTED,
            "Recovery batch was cancelled.",
            { retryable: true },
          );
          break;
        }
        const slot = index++;
        const operation = selected[slot];
        // Advance on attempted lookup, not success, so poison entries cannot
        // monopolize the beginning of every future batch.
        this.#cursor = operation.operationId;
        const attemptedAt = this.#clock();
        this.#maxWaitMs = Math.max(
          this.#maxWaitMs,
          Math.max(
            0,
            attemptedAt -
              (this.#lastVisited.get(operation.operationId) ?? operation.createdAt),
          ),
        );
        this.#lastVisited.set(operation.operationId, attemptedAt);
        try {
          const result = await lookup(operation.operationId, { signal });
          results[slot] = result;
          this.#observations += 1;
          if (result?.state === "terminal" || result?.terminalStatus != null) {
            this.#backoff.delete(operation.operationId);
          } else {
            this.#scheduleBackoff(operation.operationId, this.#clock());
          }
        } catch (error) {
          this.#failures += 1;
          if (fatal.has(error?.code)) {
            failure = error;
          } else {
            this.#scheduleBackoff(operation.operationId, this.#clock());
            results[slot] = Object.freeze({
              ...operation,
              recoveryError: error?.code ?? C.TRANSPORT,
            });
          }
        }
      }
    };
    await Promise.all(
      Array.from({ length: Math.min(concurrency, selected.length) }, worker),
    );
    this.#lastDurationMs = Math.max(0, this.#clock() - started);
    if (failure) throw failure;
    return Object.freeze(results);
  }

  #scheduleBackoff(operationId, now) {
    const attempts = (this.#backoff.get(operationId)?.attempts ?? 0) + 1;
    const exponent = Math.min(attempts - 1, 30);
    const delay = Math.min(
      this.#maxBackoffMs,
      this.#initialBackoffMs * (2 ** exponent),
    );
    this.#backoff.set(operationId, Object.freeze({
      attempts,
      nextEligibleAt: now + delay,
    }));
  }
}

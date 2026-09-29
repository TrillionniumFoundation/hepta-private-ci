export async function callWithDeadline({ call, payload, now, deadlineMs, timeoutCapMs, abortable, timeoutName }) {
  const startedAt = now();
  if (!Number.isSafeInteger(startedAt) || !Number.isSafeInteger(deadlineMs)
      || !Number.isSafeInteger(timeoutCapMs) || timeoutCapMs < 1) {
    throw new TypeError("browser call requires a valid clock and bounded deadline");
  }
  const remaining = deadlineMs - startedAt;
  if (remaining <= 0) {
    const error = new Error(`${timeoutName} deadline expired before entry`);
    error.name = timeoutName === "browser driver" ? "BrowserDriverTimeoutError" : "BrowserAuthorityTimeoutError";
    throw error;
  }
  const timeoutMs = Math.min(timeoutCapMs, remaining);
  const monotonicEnd = performance.now() + timeoutMs;
  const controller = abortable ? new AbortController() : null;
  let lastObservedAt = startedAt;
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      controller?.abort();
      const error = new Error(`${timeoutName} timed out`);
      error.name = timeoutName === "browser driver" ? "BrowserDriverTimeoutError" : "BrowserAuthorityTimeoutError";
      reject(error);
    }, timeoutMs);
  });
  try {
    const result = await Promise.race([
      Promise.resolve().then(() => {
        const current = now();
        if (!Number.isSafeInteger(current) || current < lastObservedAt) {
          throw new TypeError("browser call clock is invalid or regressed");
        }
        if (current >= deadlineMs || performance.now() >= monotonicEnd) {
          const error = new Error(`${timeoutName} deadline expired before entry`);
          error.name = timeoutName === "browser driver" ? "BrowserDriverTimeoutError" : "BrowserAuthorityTimeoutError";
          throw error;
        }
        lastObservedAt = current;
        return call(payload, controller ? { signal: controller.signal } : undefined);
      }),
      timeout,
    ]);
    // Timers cannot preempt synchronous work or a chain of microtasks. A late
    // resolved Promise must not win eligibility merely by beating the timer
    // callback. The original deadline is never restarted at completion.
    const completedAt = now();
    if (!Number.isSafeInteger(completedAt) || completedAt < lastObservedAt) {
      throw new TypeError("browser completion clock is invalid or regressed");
    }
    if (completedAt >= deadlineMs || performance.now() >= monotonicEnd) {
      controller?.abort();
      const error = new Error(`${timeoutName} deadline expired before completion`);
      error.name = timeoutName === "browser driver" ? "BrowserDriverTimeoutError" : "BrowserAuthorityTimeoutError";
      throw error;
    }
    return result;
  } finally {
    clearTimeout(timer);
  }
}

// Per existing host, not per profile: otherwise fresh profile IDs bypass the
// queue bound. Settlement retains eight slots without reordering FIFO work.
const MAX_PENDING_NORMAL = 64;
const RESERVED_SETTLEMENT_SLOTS = 8;
const pendingByOwner = new WeakMap();

export async function exclusive(lockMap, key, operation, { settlement = false } = {}) {
  const pending = pendingByOwner.get(lockMap) ?? { count: 0 };
  const limit = MAX_PENDING_NORMAL + (settlement ? RESERVED_SETTLEMENT_SLOTS : 0);
  if (pending.count >= limit) throw new TypeError("browser host queue capacity is exhausted");
  pending.count++;
  pendingByOwner.set(lockMap, pending);
  const prior = lockMap.get(key) ?? Promise.resolve();
  let release;
  const current = new Promise((resolve) => { release = resolve; });
  const tail = prior.catch(() => {}).then(() => current);
  lockMap.set(key, tail);
  await prior.catch(() => {});
  try {
    return await operation();
  } finally {
    pending.count--;
    if (pending.count === 0) pendingByOwner.delete(lockMap);
    release();
    if (lockMap.get(key) === tail) lockMap.delete(key);
  }
}

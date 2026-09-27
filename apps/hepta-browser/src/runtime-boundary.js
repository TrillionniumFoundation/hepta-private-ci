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

export async function exclusive(lockMap, key, operation) {
  const prior = lockMap.get(key) ?? Promise.resolve();
  let release;
  const current = new Promise((resolve) => { release = resolve; });
  const tail = prior.catch(() => {}).then(() => current);
  lockMap.set(key, tail);
  await prior.catch(() => {});
  try {
    return await operation();
  } finally {
    release();
    if (lockMap.get(key) === tail) lockMap.delete(key);
  }
}

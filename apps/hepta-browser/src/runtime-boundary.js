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
    return await Promise.race([
      Promise.resolve().then(() => {
        const current = now();
        if (!Number.isSafeInteger(current) || current < startedAt) {
          throw new TypeError("browser call clock is invalid or regressed");
        }
        if (current >= deadlineMs || performance.now() >= monotonicEnd) {
          const error = new Error(`${timeoutName} deadline expired before entry`);
          error.name = timeoutName === "browser driver" ? "BrowserDriverTimeoutError" : "BrowserAuthorityTimeoutError";
          throw error;
        }
        return call(payload, controller ? { signal: controller.signal } : undefined);
      }),
      timeout,
    ]);
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

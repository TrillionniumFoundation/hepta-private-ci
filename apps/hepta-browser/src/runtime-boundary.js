export async function callWithDeadline({ call, payload, now, deadlineMs, timeoutCapMs, abortable, timeoutName }) {
  const remaining = Math.max(1, deadlineMs - now());
  const timeoutMs = Math.min(timeoutCapMs, remaining);
  const controller = abortable ? new AbortController() : null;
  const timeoutError = new Error(`${timeoutName} timed out`);
  timeoutError.name =
    timeoutName === "browser driver" ? "BrowserDriverTimeoutError" : "BrowserAuthorityTimeoutError";
  let timer;
  let timedOut = false;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      timedOut = true;
      controller?.abort();
      reject(timeoutError);
    }, timeoutMs);
  });
  try {
    return await Promise.race([
      Promise.resolve().then(() => call(payload, controller ? { signal: controller.signal } : undefined)),
      timeout,
    ]);
  } catch (error) {
    // An abort-aware callee may reject synchronously from the signal handler
    // before the timeout promise wins Promise.race. Preserve the boundary
    // cause: an abort initiated by this timer is a timeout, not a driver error.
    if (timedOut && error?.name === "AbortError") throw timeoutError;
    throw error;
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

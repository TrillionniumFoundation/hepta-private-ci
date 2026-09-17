export async function callWithDeadline({ call, payload, now, deadlineMs, timeoutCapMs, abortable, timeoutName }) {
  const remaining = Math.max(1, deadlineMs - now());
  const timeoutMs = Math.min(timeoutCapMs, remaining);
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
      Promise.resolve().then(() => call(payload, controller ? { signal: controller.signal } : undefined)),
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

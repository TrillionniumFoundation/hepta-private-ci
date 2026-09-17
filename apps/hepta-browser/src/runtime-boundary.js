const DEFAULT_MAX_QUEUED_PER_KEY = 64;
const QUEUE_DEPTHS = new WeakMap();

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

function queueDepthMap(lockMap) {
  let depths = QUEUE_DEPTHS.get(lockMap);
  if (!depths) {
    depths = new Map();
    QUEUE_DEPTHS.set(lockMap, depths);
  }
  return depths;
}

export async function exclusive(
  lockMap,
  key,
  operation,
  { maxQueued = DEFAULT_MAX_QUEUED_PER_KEY } = {},
) {
  if (!(lockMap instanceof Map)) throw new TypeError("exclusive lockMap must be a Map");
  if (typeof operation !== "function") throw new TypeError("exclusive operation must be a function");
  if (!Number.isSafeInteger(maxQueued) || maxQueued < 1 || maxQueued > 4096) {
    throw new TypeError("exclusive maxQueued must be a bounded positive safe integer");
  }

  const depths = queueDepthMap(lockMap);
  const depth = depths.get(key) ?? 0;
  if (depth >= maxQueued) {
    const error = new Error("browser mutation queue capacity is exhausted");
    error.name = "BrowserBackpressureError";
    error.code = "BROWSER_BACKPRESSURE";
    throw error;
  }
  depths.set(key, depth + 1);

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
    const nextDepth = (depths.get(key) ?? 1) - 1;
    if (nextDepth <= 0) depths.delete(key);
    else depths.set(key, nextDepth);
  }
}

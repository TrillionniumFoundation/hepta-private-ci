const DEFAULT_MAX_QUEUED_PER_KEY = 64;
const QUEUE_DEPTHS = new WeakMap();

export async function callWithDeadline({
  call,
  payload,
  now,
  deadlineMs,
  timeoutCapMs,
  abortable,
  timeoutName,
}) {
  const remaining = deadlineMs - now();
  if (remaining <= 0) {
    const error = new Error(`${timeoutName} timed out`);
    error.name =
      timeoutName === "browser driver"
        ? "BrowserDriverTimeoutError"
        : "BrowserAuthorityTimeoutError";
    throw error;
  }

  // A non-abortable authority fence must never be raced by a local timer:
  // returning a timeout while the fenced consumer continues could allow a
  // durable intent and browser dispatch after the caller was told it failed.
  // The authority owner is responsible for entering the consumer only while
  // its grant is live; Browser re-checks its own deadline inside that consumer.
  if (!abortable) {
    return call(payload, undefined);
  }

  const timeoutMs = Math.min(timeoutCapMs, remaining);
  const controller = new AbortController();
  let timer;
  let timeoutError = null;
  const operation = Promise.resolve().then(() =>
    call(payload, { signal: controller.signal }),
  );
  const timeout = new Promise((resolve) => {
    timer = setTimeout(() => {
      timeoutError = new Error(`${timeoutName} timed out`);
      timeoutError.name =
        timeoutName === "browser driver"
          ? "BrowserDriverTimeoutError"
          : "BrowserAuthorityTimeoutError";
      controller.abort(timeoutError);
      resolve({ kind: "timeout" });
    }, timeoutMs);
  });

  try {
    const first = await Promise.race([
      operation.then(
        (value) => ({ kind: "value", value }),
        (error) => ({ kind: "error", error }),
      ),
      timeout,
    ]);
    if (first.kind === "value") return first.value;
    if (first.kind === "error") {
      // An abort-aware driver may reject with its own AbortError before the
      // timeout branch wins Promise.race. The timeout callback sets
      // timeoutError before aborting, so preserve the causal timeout identity.
      if (timeoutError !== null) {
        await operation.catch(() => {});
        throw timeoutError;
      }
      throw first.error;
    }

    // Do not return while an effect-capable call can still complete in the
    // background. Abort, then wait until the driver has actually settled.
    await operation.catch(() => {});
    throw timeoutError;
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
  const current = new Promise((resolve) => {
    release = resolve;
  });
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

const DEFAULT_MAX_QUEUED_PER_KEY = 64;
const DEFAULT_MAX_QUEUED_TOTAL = 1024;
const QUEUE_STATES = new WeakMap();

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

function queueState(lockMap) {
  let state = QUEUE_STATES.get(lockMap);
  if (!state) {
    state = {
      depths: new Map(),
      total: 0,
      active: 0,
      admitted: 0,
      completed: 0,
      perKeyRejects: 0,
      aggregateRejects: 0,
      maxTotal: 0,
      maxActive: 0,
      maxWaitMs: 0,
    };
    QUEUE_STATES.set(lockMap, state);
  }
  return state;
}

function boundedPositiveInteger(value, name, maximum) {
  if (!Number.isSafeInteger(value) || value < 1 || value > maximum) {
    throw new TypeError(`${name} must be a bounded positive safe integer`);
  }
}

export function exclusiveQueueSnapshot(lockMap) {
  if (!(lockMap instanceof Map)) {
    throw new TypeError("exclusive lockMap must be a Map");
  }
  const state = queueState(lockMap);
  return Object.freeze({
    admitted: state.admitted,
    completed: state.completed,
    active: state.active,
    waiting: state.total - state.active,
    admittedButUnsettled: state.total,
    maxAdmittedButUnsettled: state.maxTotal,
    maxActive: state.maxActive,
    maxWaitMs: state.maxWaitMs,
    perKeyBackpressureRejects: state.perKeyRejects,
    aggregateBackpressureRejects: state.aggregateRejects,
    perKeyDepths: Object.freeze(
      [...state.depths.entries()].map(([key, depth]) =>
        Object.freeze({ key: String(key), depth }),
      ),
    ),
  });
}

export async function exclusive(
  lockMap,
  key,
  operation,
  {
    maxQueued = DEFAULT_MAX_QUEUED_PER_KEY,
    maxQueuedTotal = DEFAULT_MAX_QUEUED_TOTAL,
    now = Date.now,
  } = {},
) {
  if (!(lockMap instanceof Map)) throw new TypeError("exclusive lockMap must be a Map");
  if (typeof operation !== "function") throw new TypeError("exclusive operation must be a function");
  if (typeof now !== "function") throw new TypeError("exclusive now must be a function");
  boundedPositiveInteger(maxQueued, "exclusive maxQueued", 4096);
  boundedPositiveInteger(maxQueuedTotal, "exclusive maxQueuedTotal", 65_536);

  const state = queueState(lockMap);
  const depth = state.depths.get(key) ?? 0;
  if (depth >= maxQueued) {
    state.perKeyRejects += 1;
    const error = new Error("browser mutation queue capacity is exhausted");
    error.name = "BrowserBackpressureError";
    error.code = "BROWSER_BACKPRESSURE";
    throw error;
  }
  if (state.total >= maxQueuedTotal) {
    state.aggregateRejects += 1;
    const error = new Error("aggregate browser mutation capacity is exhausted");
    error.name = "BrowserBackpressureError";
    error.code = "BROWSER_GLOBAL_BACKPRESSURE";
    throw error;
  }

  const enqueuedAt = Number(now());
  if (!Number.isFinite(enqueuedAt)) {
    throw new TypeError("exclusive now must return a finite number");
  }
  state.depths.set(key, depth + 1);
  state.total += 1;
  state.admitted += 1;
  state.maxTotal = Math.max(state.maxTotal, state.total);

  const prior = lockMap.get(key) ?? Promise.resolve();
  let release;
  const current = new Promise((resolve) => {
    release = resolve;
  });
  const tail = prior.catch(() => {}).then(() => current);
  lockMap.set(key, tail);
  await prior.catch(() => {});

  const startedAt = Number(now());
  if (!Number.isFinite(startedAt)) {
    release();
    throw new TypeError("exclusive now must return a finite number");
  }
  state.maxWaitMs = Math.max(state.maxWaitMs, Math.max(0, startedAt - enqueuedAt));
  state.active += 1;
  state.maxActive = Math.max(state.maxActive, state.active);

  try {
    return await operation();
  } finally {
    // Capacity remains charged until the admitted operation has actually
    // settled. Caller cancellation or a requested process termination is not a
    // cleanup receipt and therefore cannot release aggregate capacity early.
    state.active -= 1;
    state.total -= 1;
    state.completed += 1;
    release();
    if (lockMap.get(key) === tail) lockMap.delete(key);
    const nextDepth = (state.depths.get(key) ?? 1) - 1;
    if (nextDepth <= 0) state.depths.delete(key);
    else state.depths.set(key, nextDepth);
  }
}

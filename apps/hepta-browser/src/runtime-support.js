import { deadline } from "./runtime-primitives.js";

export class ProfileLockTable {
  #locks = new Map();

  async run(profileId, callback) {
    const previous = this.#locks.get(profileId) ?? Promise.resolve();
    let release;
    const current = new Promise((resolve) => { release = resolve; });
    const gate = previous.then(() => current);
    this.#locks.set(profileId, gate);
    await previous;
    try {
      return await callback();
    } finally {
      release();
      if (this.#locks.get(profileId) === gate) this.#locks.delete(profileId);
    }
  }
}

export function driverDeadline(clock, defaultTimeoutMs, requestedDeadlineMs, ceilingMs) {
  const now = clock();
  const fallback = now + defaultTimeoutMs;
  const requested = requestedDeadlineMs === undefined ? fallback : deadline(requestedDeadlineMs, now);
  const bounded = Math.min(requested, ceilingMs, fallback);
  if (bounded <= now) throw new TypeError("driver deadline has expired");
  return bounded;
}

export function recoveryDeadline(clock, defaultTimeoutMs, requestedDeadlineMs) {
  const now = clock();
  return requestedDeadlineMs === undefined ? now + defaultTimeoutMs : deadline(requestedDeadlineMs, now);
}

export async function callDriver(driver, clock, method, payload, deadlineMs) {
  const now = clock();
  if (deadlineMs <= now) throw new TypeError(`${method} driver deadline has expired`);
  const controller = new AbortController();
  const timeoutMs = Math.max(1, deadlineMs - now);
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      controller.abort(new Error(`${method} driver deadline exceeded`));
      reject(new Error(`${method} driver deadline exceeded`));
    }, timeoutMs);
  });
  try {
    return await Promise.race([
      Promise.resolve(driver[method]({ ...payload, signal: controller.signal })),
      timeout,
    ]);
  } finally {
    clearTimeout(timer);
  }
}

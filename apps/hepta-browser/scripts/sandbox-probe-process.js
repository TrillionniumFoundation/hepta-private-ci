import { readFile, readdir } from "node:fs/promises";
import { performance } from "node:perf_hooks";

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
const MAX_PROCESSES = 4096;

function fail(label, message, detail = {}) {
  return Object.assign(new Error(`${label}: ${message}`), { probe: { label, ...detail } });
}

// Qualification-only diagnostics. Keep listeners installed through `close`,
// not merely `exit`: buffered output must not be truncated into false evidence.
export function observeProbeProcess(child, {
  label = "sandbox probe", timeoutMs = 10_000, maxOutputBytes = 16_384,
} = {}) {
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 120_000 ||
      !Number.isSafeInteger(maxOutputBytes) || maxOutputBytes < 1 || maxOutputBytes > 1_048_576) {
    throw new TypeError("probe process budget is outside the hard bound");
  }
  let stdout = Buffer.alloc(0);
  let stderr = Buffer.alloc(0);
  let failure = null;
  let closed = false;
  let exit = null;
  let killTimer;
  let timer;
  let resolveCompletion;
  let rejectCompletion;
  const completion = new Promise((resolve, reject) => {
    resolveCompletion = resolve;
    rejectCompletion = reject;
  });
  // Readiness can fail before the caller awaits completion; retain the actual
  // rejection without producing a second unhandled rejection.
  completion.catch(() => {});
  const details = () => ({ pid: child.pid ?? null, exit, stdout: stdout.toString("utf8"), stderr: stderr.toString("utf8") });
  const abort = (message) => {
    if (closed || failure) return;
    failure = fail(label, message, details());
    try { child.kill("SIGKILL"); } catch {}
    // A kill request is not success. Bound even a broken pipe/process owner.
    killTimer = setTimeout(() => {
      clearTimeout(timer);
      child.stdin?.destroy(); child.stdout?.destroy(); child.stderr?.destroy();
      rejectCompletion(failure);
    }, 2_000);
  };
  const append = (which, bytes) => {
    const prior = which === "stdout" ? stdout : stderr;
    const chunk = Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes);
    const room = Math.max(0, maxOutputBytes - prior.length);
    const next = Buffer.concat([prior, chunk.subarray(0, room)]);
    if (which === "stdout") stdout = next; else stderr = next;
    if (chunk.length > room) abort(`${which} exceeds diagnostic budget`);
  };
  child.stdout?.on("data", bytes => append("stdout", bytes));
  child.stderr?.on("data", bytes => append("stderr", bytes));
  child.stdin?.on("error", error => abort(`control pipe error: ${error.message}`));
  child.on("error", error => abort(`process error: ${error.message}`));
  child.once("exit", (code, signal) => { exit = { code, signal }; });
  child.once("close", (code, signal) => {
    closed = true; exit = { code, signal };
    clearTimeout(timer); clearTimeout(killTimer);
    if (failure) rejectCompletion(Object.assign(failure, { probe: { label, ...details() } }));
    else if (code !== 0) rejectCompletion(fail(label, "process did not exit successfully", details()));
    else resolveCompletion(details());
  });
  timer = setTimeout(() => abort("process deadline exceeded"), timeoutMs);
  return {
    completion,
    get closed() { return closed; },
    get output() { return stdout.toString("utf8"); },
    async readyLine({ timeoutMs: readyTimeoutMs = timeoutMs } = {}) {
      if (!Number.isSafeInteger(readyTimeoutMs) || readyTimeoutMs < 1 || readyTimeoutMs > 120_000) {
        throw new TypeError("invalid readiness budget");
      }
      const deadline = performance.now() + Math.min(timeoutMs, readyTimeoutMs);
      while (performance.now() < deadline) {
        if (failure) throw failure;
        if (closed || exit !== null) throw fail(label, "process exited before readiness acknowledgement", details());
        const text = stdout.toString("utf8");
        const end = text.indexOf("\n");
        if (end >= 0) return text.slice(0, end);
        await sleep(10);
      }
      abort("readiness deadline exceeded");
      throw failure;
    },
  };
}

export async function probeProcessIdentity(pid) {
  if (!Number.isSafeInteger(pid) || pid < 2) throw new TypeError("invalid host process identity");
  try {
    const text = await readFile(`/proc/${pid}/stat`, "utf8");
    const end = text.lastIndexOf(") ");
    const fields = text.slice(end + 2).trim().split(/\s+/);
    if (end < 0 || !/^\d+$/.test(fields[19] ?? "")) throw new Error("malformed /proc identity");
    return Object.freeze({ pid, startTime: fields[19], parentPid: Number(fields[1]) });
  } catch (error) {
    if (error?.code === "ENOENT" || error?.code === "ESRCH") return null;
    throw error;
  }
}

// Capture host-namespace identities while the acknowledged helper is alive.
// Inspect all threads: a browser descendant need not belong to the leader.
export async function snapshotProbeTree(rootPid) {
  const queue = [rootPid];
  const seen = new Set();
  const identities = [];
  while (queue.length) {
    const pid = queue.shift();
    if (seen.has(pid)) continue;
    seen.add(pid);
    if (seen.size > MAX_PROCESSES) throw new Error("probe process census exceeds its bound");
    const identity = await probeProcessIdentity(pid);
    if (!identity) throw new Error("probe process disappeared during readiness census");
    identities.push(identity);
    const tasks = await readdir(`/proc/${pid}/task`);
    if (tasks.length > MAX_PROCESSES) throw new Error("probe task census exceeds its bound");
    let readableChildrenFiles = 0;
    for (const task of tasks) {
      let children;
      try { children = await readFile(`/proc/${pid}/task/${task}/children`, "utf8"); readableChildrenFiles++; }
      catch (error) {
        if (error?.code === "ENOENT" || error?.code === "ESRCH") continue;
        throw error;
      }
      for (const token of children.trim().split(/\s+/).filter(Boolean)) {
        const next = Number(token);
        if (!Number.isSafeInteger(next) || next < 2) throw new Error("malformed probe descendant PID");
        queue.push(next);
      }
    }
    if (readableChildrenFiles === 0) {
      // Some Linux procfs implementations omit task/children. A bounded
      // parent-PID census is valid for these READY, stationary canaries; do
      // not silently turn ENOENT for every task into an empty descendant list.
      const entries = (await readdir("/proc")).filter(name => /^[0-9]+$/.test(name));
      if (entries.length > MAX_PROCESSES) throw new Error("probe fallback census exceeds its bound");
      for (const entry of entries) {
        const next = Number(entry);
        if (next < 2) continue;
        const candidate = await probeProcessIdentity(next);
        if (candidate?.parentPid === pid) queue.push(next);
      }
    }
    if ((await probeProcessIdentity(pid))?.startTime !== identity.startTime) {
      throw new Error("probe lifetime changed during readiness census");
    }
  }
  if (identities.length < 2) throw new Error("probe readiness has no observed descendant");
  return identities;
}

export async function waitForProbeTreeExit(identities, timeoutMs = 5_000) {
  if (!Array.isArray(identities) || identities.length < 2 || identities.length > MAX_PROCESSES ||
      !Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 120_000) {
    throw new TypeError("invalid probe exit observation budget or census");
  }
  for (const value of identities) {
    if (!Number.isSafeInteger(value?.pid) || value.pid < 2 || !/^\d+$/.test(value.startTime ?? "")) {
      throw new TypeError("invalid captured probe lifetime");
    }
  }
  if (new Set(identities.map(value => value.pid)).size !== identities.length) {
    throw new TypeError("duplicate captured probe lifetime");
  }
  const deadline = performance.now() + timeoutMs;
  while (true) {
    const live = [];
    for (const identity of identities) {
      if ((await probeProcessIdentity(identity.pid))?.startTime === identity.startTime) live.push(identity);
    }
    if (live.length === 0) return;
    if (performance.now() >= deadline) throw fail("parent-death", "observed process lifetimes remain", { live });
    await sleep(10);
  }
}

// Qualification helper only. Keep the direct launcher parent alive until the
// outer oracle has captured the READY worker's host-namespace descendants.
import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import { observeProbeProcess } from "./sandbox-probe-process.js";

const [command, encodedArgs, marker] = process.argv.slice(2);
const child = spawn(command, JSON.parse(encodedArgs), { env: {}, stdio: "pipe", shell: false });
const observed = observeProbeProcess(child, { label: "parent-death worker", timeoutMs: 15_000 });
child.stdin.end();
let released = false;
let release;
const releaseRequested = new Promise(resolve => { release = resolve; });
let control = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", text => {
  control += text;
  if (control.length > 16) release(false);
  else if (control === "release\n") release(true);
  else if (control.includes("\n")) release(false);
});
process.stdin.on("end", () => release(false));
process.stdin.on("error", () => release(false));
const timer = setTimeout(() => release(false), 10_000);
try {
  const deadline = performance.now() + 5_000;
  while (true) {
    if (observed.closed || child.exitCode !== null || child.signalCode !== null) {
      await observed.completion;
      throw new Error("parent-death worker exited before ready");
    }
    let ready;
    try { ready = await readFile(marker, "utf8"); }
    catch (error) { if (error?.code !== "ENOENT") throw error; }
    if (ready === "ready\n") break;
    if (ready !== undefined) throw new Error("parent-death readiness marker mismatch");
    if (performance.now() >= deadline) throw new Error("parent-death readiness timeout");
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  await new Promise((resolve, reject) => {
    process.stdout.write(JSON.stringify({ ready: true, launcherPid: child.pid }) + "\n", error => error ? reject(error) : resolve());
  });
  if (!await releaseRequested) throw new Error("parent-death helper did not receive exact release");
  released = true;
} catch (error) {
  process.stderr.write(JSON.stringify({ message: error.message, probe: error.probe ?? null }) + "\n");
} finally {
  clearTimeout(timer);
  if (!released) {
    child.kill("SIGKILL");
    await observed.completion.catch(() => {});
  }
  // Intentional immediate exit AFTER acknowledged readiness/census. Do not
  // signal the worker on the success path: Bubblewrap must enforce parent death.
  process.exit(released ? 0 : 1);
}

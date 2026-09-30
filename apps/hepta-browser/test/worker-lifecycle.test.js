import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once, EventEmitter } from "node:events";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { OwnedBrowserChild } from "../src/worker-lifecycle.js";

function child() {
  return spawn(process.execPath, ["-e", "process.stdout.write('ready\\n');setInterval(()=>{},1000)"], {
    stdio: ["pipe", "pipe", "pipe"],
  });
}

test("termination observes real child exit and kernel disappearance", async t => {
  const process = child();
  const owner = new OwnedBrowserChild(process);
  t.after(() => process.kill("SIGKILL"));
  await once(process.stdout, "data");
  let exited = false;
  process.once("exit", () => { exited = true; });
  const proof = await owner.terminate();
  assert.equal(proof.processExitObserved, true);
  assert.equal(exited, true);
  assert.equal(owner.exited, true);
  await assert.rejects(readFile(`/proc/${process.pid}/stat`), { code: "ENOENT" });
});

test("parallel termination is idempotent for one acquired child", async t => {
  const process = child();
  const owner = new OwnedBrowserChild(process);
  t.after(() => process.kill("SIGKILL"));
  await once(process.stdout, "data");
  const [left, right] = await Promise.all([owner.terminate(), owner.terminate()]);
  assert.deepEqual(left, right);
  assert.deepEqual(await owner.terminate(), left);
});

test("kill acknowledged without close is not containment and remains retryable", async () => {
  const process = new EventEmitter();
  process.pid = undefined;
  process.kill = () => { process.killed = true; return true; };
  const owner = new OwnedBrowserChild(process);
  await assert.rejects(owner.terminate({ timeoutMs: 30 }), { code: "BROWSER_CONTAINMENT_UNPROVED" });
  assert.equal(owner.closed, false);
  process.emit("close", 0, "SIGKILL");
  assert.equal((await owner.terminate()).processExitObserved, true);
});

test("spawn failure is observed without inventing a live process", async () => {
  const process = spawn("/hepta-test-no-such-executable", [], { stdio: "pipe" });
  const owner = new OwnedBrowserChild(process);
  await new Promise(resolve => process.once("close", resolve));
  assert.equal((await owner.terminate()).processExitObserved, true);
});

test("ordinary exit followed by cleanup does not send another signal", async () => {
  const process = spawn(globalThis.process.execPath, ["-e", ""], { stdio: "pipe" });
  const owner = new OwnedBrowserChild(process);
  await new Promise(resolve => process.once("close", resolve));
  process.kill = () => { throw new Error("must not signal an exited lifetime"); };
  assert.equal((await owner.terminate()).processExitObserved, true);
});

test("termination rejects invalid and unbounded wait policies", async t => {
  const process = child();
  const owner = new OwnedBrowserChild(process);
  t.after(() => owner.terminate());
  for (const timeoutMs of [0, -1, 120_001, NaN, 1.5, true]) {
    await assert.rejects(owner.terminate({ timeoutMs }), TypeError);
  }
});

import assert from "node:assert/strict";
import test from "node:test";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { access, mkdtemp, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { SubprocessBrowserDriver } from "../src/worker-driver.js";
import { WorkerFrameDecoder, buildWorkerFrame, encodeWorkerFrame } from "../src/worker-protocol.js";

const turn = () => new Promise((resolve) => setImmediate(resolve));
const posture = Object.fromEntries(["inheritedPrivateChannel", "externalNetworkDenied",
  "ambientEnvironmentDenied", "userHomeHidden", "hostFilesystemRestricted", "parentDeathCleanup"]
  .map((name) => [name, true]));
const input = () => ({ profileId: "profile.1", generation: 1 });
function settle(promise) {
  const state = { outcome: "pending", promise: null };
  state.promise = promise.then((value) => Object.assign(state, { outcome: "resolved", value }),
    (error) => Object.assign(state, { outcome: "rejected", error }));
  return state;
}

async function fixture(t, { rejectStart = false, real = false } = {}) {
  const root = await mkdtemp(join(tmpdir(), "hepta-worker-retirement-"));
  const state = { children: [], writes: [], paths: [], killMode: "success" };
  t.after(async () => {
    for (const child of state.children) {
      try { child.kill?.("SIGKILL"); } catch { /* injected signal denial, no real child */ }
    }
    await rm(root, { recursive: true, force: true });
  });
  // This actual child speaks only a controlled test protocol. Its launcher's
  // declared posture is a fixture, not a Bubblewrap/Servo isolation claim.
  const program = `const crypto = require('node:crypto');
const canon = x => x && typeof x === 'object' ? (Array.isArray(x) ? x.map(canon) : Object.fromEntries(Object.keys(x).sort().map(k => [k, canon(x[k])]))):x;
let buffer=Buffer.alloc(0), seq=1;
process.stdin.on('data', chunk => { buffer=Buffer.concat([buffer,chunk]);
while(buffer.length>=4 && buffer.length>=buffer.readUInt32BE(0)+4) {
const n=buffer.readUInt32BE(0), req=JSON.parse(buffer.subarray(4,n+4)); buffer=buffer.subarray(n+4);
const payload={ok:true,observation:req.kind==='start'?{started:true}:{stopped:true}};
const payloadDigest=crypto.createHash('sha256').update(JSON.stringify(canon(payload))).digest('hex');
const body=Buffer.from(JSON.stringify(canon({...req,kind:'response',sequence:seq++,payload,payloadDigest})));
const h=Buffer.alloc(4);h.writeUInt32BE(body.length);process.stdout.write(Buffer.concat([h,body])); }});
setInterval(()=>{},1000);`;
  const bytes = Buffer.from(real ? program : "controlled-process-artifact");
  const workerPath = join(root, "worker.cjs");
  await writeFile(workerPath, bytes);
  const launcher = { posture, spawn({ workerPath: executable, profileDir }) {
    state.paths.push(profileDir);
    if (real) {
      const child = spawn(process.execPath, [executable], { stdio: ["pipe", "pipe", "pipe"], env: {} });
      state.children.push(child);
      return child;
    }
    const child = new EventEmitter();
    child.pid = 4000 + state.children.length;
    child.stdin = new PassThrough(); child.stdout = new PassThrough(); child.stderr = new PassThrough();
    child.kill = () => {
      if (state.killMode === "throw") throw new Error("signal denied");
      return state.killMode !== "denied";
    };
    const decoder = new WorkerFrameDecoder();
    let sequence = 1;
    child.stdin.on("data", (bytes) => {
      for (const req of decoder.push(bytes)) {
        state.writes.push(req);
        const observation = req.kind === "start" ? { started: !rejectStart } : { stopped: true };
        child.stdout.write(encodeWorkerFrame(buildWorkerFrame({ ...req, kind: "response",
          sequence: sequence++, payload: { ok: true, observation } })));
      }
    });
    state.children.push(child);
    return child;
  } };
  const driver = new SubprocessBrowserDriver({ workerPath, profileRoot: join(root, "profiles"), launcher,
    workerDigest: createHash("sha256").update(bytes).digest("hex") });
  return { driver, state, root };
}

test("stop acknowledgment is not exit; profile remains owned through exit and pipe closure", async (t) => {
  const { driver, state } = await fixture(t);
  await driver.start(input());
  const stopped = settle(driver.stop(input()));
  await turn();
  assert.equal(stopped.outcome, "pending");
  await access(state.paths[0]);
  state.children[0].emit("exit", 0, null);
  await turn();
  assert.equal(stopped.outcome, "pending", "exit alone does not close shared pipes");
  state.children[0].emit("close", 0, null);
  await stopped.promise;
  assert.equal(stopped.outcome, "resolved");
  assert.equal(stopped.value.stopped, true);
  await assert.rejects(access(state.paths[0]), { code: "ENOENT" });
});

for (const mode of ["denied", "throw"]) {
  test(`failed stop retains identity and supports cleanup-only reconciliation: ${mode}`, async (t) => {
    const { driver, state } = await fixture(t);
    await driver.start(input());
    state.killMode = mode;
    await assert.rejects(driver.stop(input()));
    await access(state.paths[0]);
    await assert.rejects(driver.start({ ...input(), generation: 2 }), /owned|started|cleanup/);
    const writes = state.writes.length;
    state.children[0].emit("exit", null, "SIGKILL");
    state.children[0].emit("close", null, "SIGKILL");
    const observed = await driver.stop(input());
    assert.equal(observed.stopped, true);
    assert.equal(state.writes.length, writes, "reconciliation must not resend stop or any effect");
  });
}

test("concurrent startup cannot overwrite a process owner", async (t) => {
  const { driver, state } = await fixture(t);
  const first = settle(driver.start(input()));
  const second = settle(driver.start({ profileId: "profile.2", generation: 2 }));
  await Promise.all([first.promise, second.promise]);
  assert.equal(first.outcome, "resolved");
  assert.equal(second.outcome, "rejected");
  assert.equal(state.children.length, 1);
});

test("startup captures immutable profile identity before asynchronous artifact reads", async (t) => {
  const { driver, state } = await fixture(t);
  const request = input();
  const started = driver.start(request);
  request.profileId = "substituted";
  request.generation = 9;
  await started;
  assert.equal(state.writes[0].sessionId, "profile.1");
  assert.equal(state.writes[0].generation, 1);
});

test("cancelled startup does not create profile files or launch a process", async (t) => {
  const { driver, state, root } = await fixture(t);
  const controller = new AbortController(); controller.abort();
  await assert.rejects(driver.start(input(), { signal: controller.signal }));
  assert.equal(state.children.length, 0);
  assert.deepEqual((await readdir(root)).sort(), ["worker.cjs"]);
});

test("same-generation startup remains excluded after observed retirement", async (t) => {
  const { driver, state } = await fixture(t);
  await driver.start(input());
  const stopped = settle(driver.stop(input()));
  await turn();
  state.children[0].emit("exit", 0, null); state.children[0].emit("close", 0, null);
  await stopped.promise;
  await assert.rejects(driver.start(input()), /generation/);
});

test("repeating an observed stop returns history without touching a new process", async (t) => {
  const { driver, state } = await fixture(t);
  const started = await driver.start(input());
  const old = { ...input(), processId: started.processId };
  const stopped = settle(driver.stop(old));
  await turn();
  state.children[0].emit("exit", 0, null); state.children[0].emit("close", 0, null);
  await stopped.promise;
  await driver.start({ ...input(), generation: 2 });
  const count = state.writes.length;
  const historical = await driver.stop(old);
  assert.equal(historical.stopped, true);
  assert.equal(state.writes.length, count);
});

test("real child stop waits for actual exit and stdio closure before removing its profile", async (t) => {
  const { driver, state } = await fixture(t, { real: true });
  await driver.start(input());
  let closed = false;
  state.children[0].on("close", () => { closed = true; });
  const stopped = await driver.stop(input());
  assert.equal(stopped.stopped, true);
  assert.equal(closed, true);
  assert.ok(state.children[0].exitCode !== null || state.children[0].signalCode !== null);
  await assert.rejects(access(state.paths[0]), { code: "ENOENT" });
});

test("a bounded cleanup timeout retains ownership and a later close reconciles without I/O", async (t) => {
  const { driver, state } = await fixture(t);
  await driver.start(input());
  await assert.rejects(driver.stop(input()), /unobserved.*retained/);
  await access(state.paths[0]);
  await assert.rejects(driver.start({ ...input(), generation: 2 }), /owned/);
  const count = state.writes.length;
  state.children[0].emit("exit", null, "SIGKILL"); state.children[0].emit("close", null, "SIGKILL");
  assert.equal((await driver.stop(input())).stopped, true);
  assert.equal(state.writes.length, count);
});

test("cancelled cleanup retains ownership, blocks effects and supports later retirement", async (t) => {
  const { driver, state } = await fixture(t);
  await driver.start(input());
  const controller = new AbortController();
  const stopped = settle(driver.stop(input(), { signal: controller.signal }));
  await turn(); controller.abort();
  await stopped.promise;
  assert.equal(stopped.outcome, "rejected");
  const writes = state.writes.length;
  await assert.rejects(driver.observe(input()), /retiring/);
  assert.equal(state.writes.length, writes);
  await access(state.paths[0]);
  state.children[0].emit("exit", 0, null); state.children[0].emit("close", 0, null);
  assert.equal((await driver.stop(input())).stopped, true);
});

test("failed startup retains the launched process when signalling is denied", async (t) => {
  const { driver, state } = await fixture(t, { rejectStart: true });
  state.killMode = "denied";
  await assert.rejects(driver.start(input()), /cleanup remains owned/);
  await access(state.paths[0]);
  await assert.rejects(driver.start({ ...input(), generation: 2 }), /owned/);
  const count = state.writes.length;
  state.children[0].emit("exit", 0, null); state.children[0].emit("close", 0, null);
  assert.equal((await driver.stop(input())).stopped, true);
  assert.equal(state.writes.length, count);
});

test("concurrent stop does not add a second stop request or cleanup waiter", async (t) => {
  const { driver, state } = await fixture(t);
  await driver.start(input());
  const stopped = settle(driver.stop(input()));
  await turn();
  const writes = state.writes.length;
  await assert.rejects(driver.stop(input()), /in progress/);
  assert.equal(state.writes.length, writes);
  state.children[0].emit("exit", 0, null); state.children[0].emit("close", 0, null);
  await stopped.promise;
  assert.equal(stopped.outcome, "resolved");
});

test("sequential different profiles preserve separate generation frontiers", async (t) => {
  const { driver, state } = await fixture(t);
  for (const profileId of ["profile.1", "profile.2"]) {
    const current = { profileId, generation: 1 };
    await driver.start(current);
    const stopped = settle(driver.stop(current));
    await turn();
    state.children.at(-1).emit("exit", 0, null); state.children.at(-1).emit("close", 0, null);
    await stopped.promise;
    assert.equal(stopped.outcome, "resolved");
  }
  await assert.rejects(driver.start(input()), /generation/);
  const count = state.writes.length;
  assert.equal((await driver.stop(input())).stopped, true);
  assert.equal(state.writes.length, count);
});

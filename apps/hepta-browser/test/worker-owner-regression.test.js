import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";
import { PooledSubprocessBrowserDriver, SubprocessBrowserDriver } from "../src/worker-driver.js";

const D1 = "1".repeat(64);
const protocol = new URL("../src/worker-protocol.js", import.meta.url).href;
// A real OS child speaking the actual private protocol. This is transport and
// owner qualification, not a Servo/WebView or Bubblewrap test.
const worker = `const { readFileSync } = require('node:fs');
import(${JSON.stringify(protocol)}).then(({WorkerFrameDecoder,buildWorkerFrame,encodeWorkerFrame})=>{
  const decoder=new WorkerFrameDecoder();let sequence=1;
  process.stdin.on('data', chunk=>{
    for(const request of decoder.push(chunk)){
      if(process.env.HOLD_START==='1' && request.kind==='start') continue;
      if(process.env.HOLD_DISPATCH==='1' && request.kind==='dispatch') continue;
      const binding={requestKind:request.kind,requestPayloadDigest:request.payloadDigest,requestSequence:request.sequence};
      const emit=(kind,payload)=>process.stdout.write(encodeWorkerFrame(buildWorkerFrame({
        sessionId:request.sessionId,generation:request.generation,sequence:sequence++,kind,requestId:request.requestId,payload
      })));
      if(request.kind==='dispatch') emit('dispatch_boundary',{...binding,localDispatchCrossed:true});
      const observation=request.kind==='start'?{started:true}:request.kind==='stop'?{stopped:true}:{terminalObserved:false};
      emit('response',{...binding,ok:true,observation});
    }
  });
  setInterval(()=>{},1000);
});`;

function input(overrides = {}) {
  return { profileId: "p", principalId: "principal", generation: 1,
    manifestDigest: D1, grantDigest: D1, expiresAtMs: Date.now() + 60_000,
    allowedOrigins: [], ...overrides };
}

async function setup(t, { pooled = false, env = {} } = {}) {
  const root = await mkdtemp("/tmp/bwo-");
  const profileRoot = join(root, "profiles");
  const workerPath = join(root, "worker.cjs");
  await writeFile(workerPath, worker, { mode: 0o500 });
  const children = [];
  const specs = [];
  const launcher = {
    posture: { sourceContractOnly: true, inheritedPrivateChannel: true,
      externalNetworkDenied: true, ambientEnvironmentDenied: true,
      userHomeHidden: true, hostFilesystemRestricted: true,
      parentDeathCleanup: true, resourceLimitsConfigured: true },
    async verify() {},
    spawn(spec) {
      specs.push(spec);
      const child = spawn(process.execPath, [spec.workerPath], { stdio: "pipe", env });
      children.push(child);
      return child;
    },
  };
  const config = { workerPath, workerDigest: createHash("sha256").update(worker).digest("hex"),
    profileRoot, launcher, maxProfiles: 1 };
  const driver = pooled ? new PooledSubprocessBrowserDriver(config) : new SubprocessBrowserDriver(config);
  t.after(async () => {
    for (const child of children) {
      if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
    }
    await Promise.all(children.map(child => child.exitCode !== null || child.signalCode !== null
      ? undefined : new Promise(resolve => child.once("exit", resolve))));
    await rm(root, { recursive: true, force: true });
  });
  return { driver, children, specs, profileRoot, root };
}

test("maximum profile identity fits pathname and preserves exact ownership manifest", async t => {
  const { driver, specs, profileRoot } = await setup(t);
  const request = input({ profileId: "P".repeat(128), principalId: "Q".repeat(128) });
  const started = await driver.start(request);
  const name = (await readdir(profileRoot)).find(name => name.startsWith(".hepta-profile-owner."));
  const owner = JSON.parse(await readFile(join(profileRoot, name), "utf8"));
  assert.equal(owner.profileId, request.profileId);
  assert.equal(owner.principalId, request.principalId);
  assert.ok(Buffer.byteLength(join(specs[0].profileDir, ".hepta-egress.sock")) <= 103);
  assert.equal(started.privateProfileDirectory, specs[0].profileDir);
  await driver.stop({ profileId: request.profileId, generation: 1, processId: started.processId });
  assert.deepEqual(await readdir(profileRoot), []);
});

test("real private child has exited before contain returns", async t => {
  const { driver, children, profileRoot } = await setup(t);
  const started = await driver.start(input());
  const result = await driver.contain({ profileId: "p", generation: 1, processId: started.processId });
  assert.equal(result.contained, true);
  assert.equal(result.processExitObserved, true);
  await assert.rejects(readFile(`/proc/${children[0].pid}/stat`), { code: "ENOENT" });
  await assert.rejects(driver.observe({ profileId: "p", generation: 1 }), /not started|quarantined/);
  await driver.stop({ profileId: "p", generation: 1 });
  assert.deepEqual(await readdir(profileRoot), []);
});

test("abort while admission is missing observes exit before returning failure", async t => {
  const { driver, children } = await setup(t, { env: { HOLD_DISPATCH: "1" } });
  await driver.start(input());
  await assert.rejects(driver.dispatch({ profileId: "p", profileGeneration: 1, operationId: "o" },
    { signal: AbortSignal.timeout(60) }), /abort|closed|exit/i);
  await assert.rejects(readFile(`/proc/${children[0].pid}/stat`), { code: "ENOENT" });
  await driver.stop({ profileId: "p", generation: 1 });
});

test("startup abort does not leave process, broker or staging ownership behind", async t => {
  const { driver, children, profileRoot } = await setup(t, { env: { HOLD_START: "1" } });
  await assert.rejects(driver.start(input(), { signal: AbortSignal.timeout(80) }), /abort/i);
  assert.equal(driver.hasPendingCleanup, false);
  await assert.rejects(readFile(`/proc/${children[0].pid}/stat`), { code: "ENOENT" });
  assert.deepEqual(await readdir(profileRoot), []);
});

test("failed filesystem cleanup retains pool capacity and same-owner retry succeeds", async t => {
  const { driver, profileRoot } = await setup(t, { pooled: true });
  await driver.start(input());
  const name = (await readdir(profileRoot)).find(name => name.startsWith(".hepta-profile-owner."));
  const path = join(profileRoot, name);
  // Force a real deterministic unlink error, including under privileged tests.
  await rm(path);
  await mkdir(path);
  await assert.rejects(driver.stop({ profileId: "p", generation: 1 }), /cleanup/);
  await assert.rejects(driver.start(input({ profileId: "next" })), { code: "BROWSER_PROFILE_CAPACITY" });
  await rm(path, { recursive: true });
  await driver.stop({ profileId: "p", generation: 1 });
  await driver.start(input({ profileId: "next" }));
  await driver.stop({ profileId: "next", generation: 1 });
  assert.deepEqual(await readdir(profileRoot), []);
});

test("simultaneous direct starts cannot acquire two workers", async t => {
  const { driver, children } = await setup(t);
  const first = driver.start(input());
  await assert.rejects(driver.start(input({ profileId: "other" })), /already started/);
  await first;
  assert.equal(children.length, 1);
  await driver.stop({ profileId: "p", generation: 1 });
});

test("lease expiry closes the actual worker and leaves cleanup explicit", async t => {
  const { driver, children } = await setup(t);
  await driver.start(input({ expiresAtMs: Date.now() + 250 }));
  await new Promise(resolve => setTimeout(resolve, 350));
  await assert.rejects(readFile(`/proc/${children[0].pid}/stat`), { code: "ENOENT" });
  await assert.rejects(driver.observe({ profileId: "p", generation: 1 }), /not started|quarantined/);
  await driver.stop({ profileId: "p", generation: 1 });
  assert.equal(driver.hasPendingCleanup, false);
});


test("a pool cannot claim stopped or contained while startup is pending", async t => {
  const { driver, children } = await setup(t, { pooled: true, env: { HOLD_START: "1" } });
  const controller = new AbortController();
  const opening = driver.start(input(), { signal: controller.signal });
  const rejected = assert.rejects(opening, /abort/i);
  await assert.rejects(driver.stop({ profileId: "p", generation: 1 }), /starting/);
  await assert.rejects(driver.contain({ profileId: "p", generation: 1 }), /starting/);
  while (children.length === 0) await new Promise(resolve => setTimeout(resolve, 5));
  controller.abort();
  await rejected;
  assert.deepEqual(await driver.stop({ profileId: "p", generation: 1 }), { stopped: true });
});

test("concurrent stops share full retirement and new dispatch is fenced immediately", async t => {
  const { driver } = await setup(t);
  await driver.start(input());
  const first = driver.stop({ profileId: "p", generation: 1 });
  await assert.rejects(driver.dispatch({ profileId: "p", profileGeneration: 1, operationId: "late" }),
    /quarantined|not started/);
  const second = driver.stop({ profileId: "p", generation: 1 });
  assert.deepEqual(await first, { stopped: true });
  assert.deepEqual(await second, { stopped: true });
  assert.equal(driver.hasPendingCleanup, false);
});

test("unstarted cleanup rejects null or missing process ownership tuples", async t => {
  const { driver } = await setup(t);
  await assert.rejects(driver.contain({ profileId: null, generation: null }), /profileId/);
  await assert.rejects(driver.stop({ profileId: "p" }), /generation/);
});

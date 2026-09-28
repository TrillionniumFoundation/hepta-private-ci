import assert from "node:assert/strict";
import test from "node:test";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { createHash } from "node:crypto";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { SubprocessBrowserDriver } from "../src/worker-driver.js";
import { WorkerFrameDecoder, buildWorkerFrame, encodeWorkerFrame } from "../src/worker-protocol.js";

const turn = () => new Promise((resolve) => setImmediate(resolve));
const D = "1".repeat(64);
function settled(promise) {
  const state = { outcome: "pending" };
  promise.then((value) => Object.assign(state, { outcome: "resolved", value }),
    (error) => Object.assign(state, { outcome: "rejected", error }));
  return state;
}

async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), "hepta-worker-channel-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const bytes = Buffer.from("controlled-worker-fixture");
  const workerPath = join(root, "worker");
  await writeFile(workerPath, bytes);
  const child = new EventEmitter();
  child.pid = 4242;
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.stdin = new EventEmitter();
  const state = { writes: [], callbacks: [], kills: 0, mode: "normal", sequence: 1 };
  child.kill = () => { state.kills++; return true; };
  child.stdin.end = () => {};
  const decoder = new WorkerFrameDecoder();
  state.frame = (request, payload = { ok: true, observation: {} }, overrides = {}) => encodeWorkerFrame(
    buildWorkerFrame({ ...request, kind: "response", sequence: state.sequence++, payload, ...overrides }),
  );
  child.stdin.write = (buffer, callback) => {
    if (state.mode === "throw") throw new Error("synchronous write failure");
    const [request] = decoder.push(buffer);
    state.writes.push(request);
    if (request.kind === "start") {
      child.stdout.write(state.frame(request, { ok: true, observation: { started: true } }));
      callback();
    } else if (state.mode === "error") callback(new Error("uncertain write failure"));
    else if (state.mode === "held") state.callbacks.push(callback);
    else callback();
    return true;
  };
  const posture = Object.fromEntries(["inheritedPrivateChannel", "externalNetworkDenied",
    "ambientEnvironmentDenied", "userHomeHidden", "hostFilesystemRestricted", "parentDeathCleanup"]
    .map((name) => [name, true]));
  const driver = new SubprocessBrowserDriver({ workerPath, profileRoot: join(root, "profiles"),
    workerDigest: createHash("sha256").update(bytes).digest("hex"),
    launcher: { posture, spawn: () => child } });
  await driver.start({ profileId: "profile.1", generation: 1 });
  const input = { profileId: "profile.1", generation: 1, processId: "servo.pid.4242" };
  const request = (operationId = "op.1", extra = {}) => driver.reconcile({ ...input, operationId, ...extra });
  return { driver, child, state, request, input };
}

async function fenced(f) {
  const before = f.state.writes.length;
  const next = settled(f.request("op.after-failure"));
  await turn();
  assert.equal(f.state.writes.length, before, "a failed channel must do no more transport I/O");
  assert.equal(next.outcome, "rejected");
}

for (const event of ["end", "error"]) {
  test(`worker stdout ${event} rejects pending work and closes admission`, async (t) => {
    const f = await fixture(t);
    const first = settled(f.request());
    assert.doesNotThrow(() => f.child.stdout.emit(event, new Error("stream failed")));
    await turn();
    assert.equal(first.outcome, "rejected");
    await fenced(f);
  });
}

for (const stream of ["stdin", "stderr"]) {
  test(`worker ${stream} error cannot escape the host event handler`, async (t) => {
    const f = await fixture(t);
    const first = settled(f.request());
    assert.doesNotThrow(() => f.child[stream].emit("error", new Error("stream failed")));
    await turn();
    assert.equal(first.outcome, "rejected");
    await fenced(f);
  });
}

for (const overrides of [{ generation: 2 }, { sequence: 9 }, { requestId: "unknown" }]) {
  test(`worker invalid reply permanently fences before child exit: ${JSON.stringify(overrides)}`, async (t) => {
    const f = await fixture(t);
    const first = settled(f.request());
    f.child.stdout.write(f.state.frame(f.state.writes.at(-1), undefined, overrides));
    await turn();
    assert.equal(first.outcome, "rejected");
    await fenced(f);
  });
}

test("malformed observation is a channel error, not an uncaught exception or lost promise", async (t) => {
  const f = await fixture(t);
  const first = settled(f.request());
  assert.doesNotThrow(() => f.child.stdout.write(f.state.frame(f.state.writes.at(-1),
    { ok: true, observation: [] })));
  await turn();
  assert.equal(first.outcome, "rejected");
  await fenced(f);
});

test("whole worker reply batch is validated before any success is published", async (t) => {
  const f = await fixture(t);
  const first = settled(f.request());
  const request = f.state.writes.at(-1);
  f.child.stdout.write(Buffer.concat([f.state.frame(request),
    f.state.frame(request, undefined, { generation: 2, requestId: "other" })]));
  await turn();
  assert.equal(first.outcome, "rejected", "valid prefix must not escape an invalid batch");
  await fenced(f);
});

for (const mode of ["throw", "error"]) {
  test(`uncertain ${mode} write closes the worker channel`, async (t) => {
    const f = await fixture(t);
    f.state.mode = mode;
    const first = settled(f.request());
    await turn();
    assert.equal(first.outcome, "rejected");
    f.state.mode = "normal";
    await fenced(f);
  });
}

test("invalid complete encoding does not consume outgoing sequence", async (t) => {
  const f = await fixture(t);
  const invalid = settled(f.request("op.invalid", { padding: "x".repeat(1_048_576) }));
  await turn();
  assert.equal(invalid.outcome, "rejected");
  const valid = settled(f.request());
  const request = f.state.writes.at(-1);
  assert.equal(request.sequence, 2);
  f.child.stdout.write(f.state.frame(request));
  await turn();
  assert.equal(valid.outcome, "resolved");
});

test("duplicate live identity does not consume outgoing sequence", async (t) => {
  const f = await fixture(t);
  const first = settled(f.request());
  const repeated = settled(f.request());
  await turn();
  assert.equal(repeated.outcome, "rejected");
  f.child.stdout.write(f.state.frame(f.state.writes.at(-1)));
  await turn();
  assert.equal(first.outcome, "resolved");
  settled(f.request("next"));
  assert.equal(f.state.writes.at(-1).sequence, 3);
});

test("worker pending requests have a hard capacity before transport I/O", async (t) => {
  const f = await fixture(t);
  const requests = Array.from({ length: 9 }, (_, i) => settled(f.request(`op.${i}`)));
  await turn();
  assert.equal(f.state.writes.length, 9, "start plus eight admitted requests");
  assert.equal(requests.at(-1).outcome, "rejected");
});

test("pending worker output bytes are bounded independently of response count", async (t) => {
  const f = await fixture(t);
  f.state.mode = "held";
  const requests = Array.from({ length: 6 }, (_, i) => settled(f.request(`op.${i}`,
    { padding: "x".repeat(750_000) })));
  await turn();
  assert.equal(f.state.writes.length, 6, "start plus five writes within four MiB");
  assert.equal(requests.at(-1).outcome, "rejected");
});

test("bounded diagnostics are drained without accumulating raw worker output", async (t) => {
  const f = await fixture(t);
  const first = settled(f.request());
  f.child.stderr.write(Buffer.alloc(16_385));
  await turn();
  assert.equal(first.outcome, "rejected");
  await fenced(f);
});

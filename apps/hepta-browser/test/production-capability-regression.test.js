import assert from "node:assert/strict";
import test from "node:test";
import { PassThrough } from "node:stream";
import {
  AgentdBrowserChannel, BrowserAgentdService, EffectAdmissionBrowserDriver,
  ParentFinalUseAuthority,
} from "../src/agentd-service.js";
import { buildAgentdBrowserFrame } from "../src/agentd-protocol.js";

class ClassDriver {
  supportsAbort = true;
  maxActiveProfiles = 1;
  maxOutstandingOperations = 1;
  async start() { return { started: true, processId: "test.driver" }; }
  async observe() { return { observed: true }; }
  async dispatch() { return { terminalObserved: false }; }
  async reconcile() { return { terminalObserved: false }; }
  async reconcilePersisted() { return { terminalObserved: false }; }
  async contain() { return { contained: true }; }
  async stop() { return { stopped: true }; }
}

class ClassHost {
  #observations = 0;
  async openProfile() { return {}; }
  async admitEffectGrant() { return {}; }
  async observePage() { return { observations: ++this.#observations }; }
  async navigateOrAct() { throw new Error("test must not dispatch"); }
  async reconcileOperation() { return {}; }
  async reconcilePersistedOperation() { return {}; }
  async closeProfile() { return {}; }
}

function channels(t) {
  const toChild = new PassThrough();
  const toParent = new PassThrough();
  const parent = new AgentdBrowserChannel({ input: toParent, output: toChild });
  const child = new AgentdBrowserChannel({ input: toChild, output: toParent });
  const close = () => { toChild.end(); toParent.end(); };
  t.after(close);
  return { parent, child, close, authority: new ParentFinalUseAuthority(child) };
}

test("production admission decorator accepts prototype methods on class drivers", () => {
  const driver = new EffectAdmissionBrowserDriver({ driver: new ClassDriver() });
  assert.equal(driver.maxActiveProfiles, 1);
  assert.equal(driver.supportsAbort, true);
});

test("production service accepts a class host and preserves private state binding", async (t) => {
  const pair = channels(t);
  const service = new BrowserAgentdService({ host: new ClassHost(), channel: pair.child, authority: pair.authority });
  const running = service.run();
  for (let number = 1; number <= 2; number++) {
    await pair.parent.send("request", `request.${number}`, { method: "observe_page", input: {} });
    const reply = await pair.parent.nextFrame();
    assert.deepEqual(reply.payload, { ok: true, result: { observations: number } });
  }
  pair.close();
  await running;
});

test("capability admission does not weaken plain JSON frame validation", () => {
  assert.throws(() => buildAgentdBrowserFrame({ sequence: 1, kind: "request",
    requestId: "request.bad", payload: new ClassHost() }), /plain object/);
  for (const driver of [null, [], {}, { supportsAbort: true }]) {
    assert.throws(() => new EffectAdmissionBrowserDriver({ driver }), TypeError);
  }
});

test("unknown service request fields reject before invoking the class host", async (t) => {
  const pair = channels(t);
  const service = new BrowserAgentdService({ host: new ClassHost(), channel: pair.child, authority: pair.authority });
  const running = service.run();
  await pair.parent.send("request", "request.extra", { method: "observe_page", input: {}, trusted: true });
  const rejected = await pair.parent.nextFrame();
  assert.equal(rejected.payload.ok, false);
  assert.match(rejected.payload.error, /unknown fields/);
  await pair.parent.send("request", "request.valid", { method: "observe_page", input: {} });
  assert.equal((await pair.parent.nextFrame()).payload.result.observations, 1);
  pair.close();
  await running;
});

test("unknown authority-enter fields cannot enter the effect consumer", async (t) => {
  const pair = channels(t);
  let entered = false;
  const request = { requestDigest: "1".repeat(64), authorityEpoch: 1 };
  const execution = pair.authority.withRequest("request.effect", () =>
    pair.authority.withVerifiedUse(request, async () => { entered = true; return {}; }));
  const rejection = assert.rejects(execution, /unknown fields/);
  assert.equal((await pair.parent.nextFrame()).kind, "authority_challenge");
  await pair.parent.send("authority_enter", "request.effect", {
    ...request, authorized: true, witnessDigest: "2".repeat(64), arbitraryAuthority: true,
  });
  await rejection;
  assert.equal(entered, false);
});

test("driver observation failures are promise rejections like other async operations", async () => {
  const driver = new EffectAdmissionBrowserDriver({ driver: new ClassDriver() });
  await assert.rejects(driver.observe({ profileId: "profile.absent", generation: 1 }), /not started/);
});

for (const replacement of ["semantic", "witness"]) {
  test(`admission rejects ${replacement} replacement before acknowledging the boundary`, async (t) => {
    const { canonicalDigest } = await import("../src/runtime-contract.js");
    const pair = channels(t);
    const emitted = [];
    const send = pair.child.send.bind(pair.child);
    t.mock.method(pair.child, "send", (kind, ...args) => {
      emitted.push(kind);
      return send(kind, ...args);
    });
    const semantics = { authorityEpoch: 1, operationId: "operation.binding",
      profileGeneration: 1, pageGeneration: 0 };
    const witness = "2".repeat(64);
    const request = { ...semantics, requestDigest: canonicalDigest(semantics) };
    const wrongDigest = replacement === "semantic" ? "3".repeat(64) : canonicalDigest({
      ...semantics, verifiedUseTokenWitnessDigest: "4".repeat(64),
    });
    const execution = pair.authority.withRequest("request.binding", () =>
      pair.authority.withVerifiedUse(request, async () => ({ admission: {
        kind: "BrowserEffectAdmissionV1", operationId: semantics.operationId,
        semanticDigest: wrongDigest, workerGeneration: 1, pageRevision: 0,
        admittedAt: Date.now(), durableOrRecoverable: true,
      } })));
    const rejected = assert.rejects(execution, /semantic digest/);
    assert.equal((await pair.parent.nextFrame()).kind, "authority_challenge");
    await pair.parent.send("authority_enter", "request.binding", {
      authorized: true, witnessDigest: witness, authorityEpoch: 1,
      requestDigest: request.requestDigest,
    });
    await rejected;
    assert.deepEqual(emitted, ["authority_challenge"]);
  });
}

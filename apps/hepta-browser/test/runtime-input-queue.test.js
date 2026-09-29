import assert from "node:assert/strict";
import test from "node:test";
import { browserActionDigest } from "../src/action.js";
import { BrowserProfileHost } from "../src/runtime.js";
import { MemoryBrowserOperationJournal } from "../src/journal.js";
import { exclusive } from "../src/runtime-boundary.js";

const D = "1".repeat(64);
const E = "5".repeat(64);
const NAV = { kind: "navigate", url: "https://example.com/a", policyDigest: D, expectedRevision: 1 };
const grant = () => ({ grantDigest: E, action: "navigate", destinationOrigin: "https://example.com",
  finalPayloadDigest: browserActionDigest(NAV), authorityEpoch: 1, expiresAtMs: 9500 });
const profile = (id = "p.1") => ({ profileId: id, principalId: "owner.1", generation: 1,
  manifestDigest: D, grantDigest: D, expiresAtMs: 10000,
  allowedOrigins: ["https://example.com"], effectGrants: [grant()] });
const identity = (id = "p.1") => ({ profileId: id, principalId: "owner.1", generation: 1 });
const operation = (id = "p.1") => ({ ...identity(id), operationId: "op.1", pageGeneration: 0,
  typedAction: { ...NAV }, destinationOrigin: "https://example.com", finalPayloadDigest: browserActionDigest(NAV),
  effectGrantDigest: E, authorityEpoch: 1, deadlineMs: 9000 });
const defer = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };
const turn = () => new Promise((resolve) => setImmediate(resolve));

function fixture(overrides = {}) {
  const calls = [];
  let page = 0;
  let now = 1000;
  const journal = new MemoryBrowserOperationJournal();
  const driver = {
    async start(input) { calls.push(["start", input]); return { started: true, processId: `process.${input.profileId}` }; },
    async observe(input) { calls.push(["observe", input]); return { pageGeneration: ++page, documentDigest: D, origin: "https://example.com" }; },
    async dispatch(input) { calls.push(["dispatch", input]); return { terminalObserved: false }; },
    async reconcile(input) { calls.push(["reconcile", input]); return { terminalObserved: true, status: "succeeded", outcomeDigest: D }; },
    async stop(input) { calls.push(["stop", input]); return { stopped: true }; },
    ...overrides,
  };
  const host = new BrowserProfileHost({ driver, journal, clock: () => now, driverCallTimeoutMs: 2000,
    authority: { async withVerifiedUse(request, consumer) {
      return consumer({ authorized: true, witnessDigest: D, authorityEpoch: request.authorityEpoch, requestDigest: request.requestDigest });
    } } });
  return { host, calls, journal, setNow(value) { now = value; } };
}

test("profile admission captures principal, generation, origins and nested grants before queueing", async () => {
  const { host, calls } = fixture();
  const request = profile();
  const pending = host.openProfile(request);
  request.principalId = "substitute";
  request.generation = 2;
  request.allowedOrigins[0] = "https://other.example";
  request.effectGrants[0].destinationOrigin = "https://other.example";
  const result = await pending;
  assert.equal(result.principalId, "owner.1");
  assert.equal(result.generation, 1);
  assert.deepEqual(calls[0][1].allowedOrigins, ["https://example.com"]);
  assert.equal((await host.navigateOrAct(operation())).operationId, "op.1");
});

test("observation cannot switch profiles after selecting its lock", async () => {
  const { host } = fixture();
  await host.openProfile(profile());
  await host.openProfile(profile("p.2"));
  const request = { ...identity(), observationBudget: 10 };
  const pending = host.observePage(request);
  request.profileId = "p.2";
  request.observationBudget = 20;
  assert.equal((await pending).profileId, "p.1");
});

test("effect captures the original profile, operation and nested typed action", async () => {
  const { host, calls } = fixture();
  await host.openProfile(profile());
  await host.openProfile(profile("p.2"));
  const request = operation();
  const pending = host.navigateOrAct(request);
  request.profileId = "p.2";
  request.operationId = "op.substitute";
  request.typedAction.url = "https://example.com/substitute";
  const result = await pending;
  assert.equal(result.profileId, "p.1");
  assert.equal(result.operationId, "op.1");
  assert.equal(calls.find(([kind]) => kind === "dispatch")[1].typedAction.url, NAV.url);
});

test("grant admission captures its original nested grant", async () => {
  const { host } = fixture();
  await host.openProfile({ ...profile(), effectGrants: [] });
  const request = { ...identity(), effectGrant: grant() };
  const pending = host.admitEffectGrant(request);
  request.effectGrant.finalPayloadDigest = "9".repeat(64);
  await pending;
  assert.equal((await host.navigateOrAct(operation())).operationId, "op.1");
});

for (const method of ["reconcileOperation", "reconcilePersistedOperation"]) {
  test(`${method} preserves the original owner and operation while waiting`, async () => {
    const { host } = fixture();
    await host.openProfile(profile());
    await host.navigateOrAct(operation());
    const request = operation();
    const pending = host[method](request);
    request.principalId = "substitute";
    request.operationId = "different";
    request.typedAction.url = "https://example.com/substitute";
    const result = await pending;
    assert.equal(result.operationId, "op.1");
    assert.equal(result.terminalObserved, true);
  });
}

test("close cannot retire a different profile after queueing", async () => {
  const { host, calls } = fixture();
  await host.openProfile(profile());
  await host.openProfile(profile("p.2"));
  const request = identity();
  const pending = host.closeProfile(request);
  request.profileId = "p.2";
  assert.equal((await pending).profileId, "p.1");
  assert.equal(calls.find(([kind]) => kind === "stop")[1].profileId, "p.1");
  assert.equal((await host.observePage({ ...identity("p.2"), observationBudget: 1 })).profileId, "p.2");
});

test("captured inputs do not cache a live grant across queue delay", async () => {
  const { host, setNow, calls } = fixture();
  await host.openProfile(profile());
  const pending = host.navigateOrAct(operation());
  setNow(10000);
  await assert.rejects(pending, /expired/);
  assert.equal(calls.filter(([kind]) => kind === "dispatch").length, 0);
});

test("executable input getters are rejected without running them", async () => {
  const { host, calls } = fixture();
  let reads = 0;
  const request = profile();
  Object.defineProperty(request, "principalId", { get() { reads++; return "owner.1"; } });
  await assert.rejects(host.openProfile(request), /data/);
  assert.equal(reads, 0);
  assert.equal(calls.length, 0);
});

test("array capacity is checked before copying index values", async () => {
  const { host } = fixture();
  const request = profile();
  const origins = new Array(129);
  let reads = 0;
  Object.defineProperty(origins, 0, { get() { reads++; return "https://example.com"; } });
  request.allowedOrigins = origins;
  await assert.rejects(host.openProfile(request), /bounded/);
  assert.equal(reads, 0);
});

test("bounded host queue retains settlement admission without spending normal capacity", async () => {
  const entered = defer();
  const release = defer();
  let observations = 0;
  const { host } = fixture({ async observe() {
    if (observations === 0) { entered.resolve(); await release.promise; }
    return { pageGeneration: ++observations, documentDigest: D, origin: "https://example.com" };
  } });
  await host.openProfile(profile());
  const read = () => host.observePage({ ...identity(), observationBudget: 1 });
  const requests = [read()];
  await entered.promise;
  for (let index = 1; index < 64; index++) requests.push(read());
  let overload;
  const excess = read().catch((error) => { overload = error; });
  const close = host.closeProfile(identity());
  try { await turn(); } finally { release.resolve(); }
  await Promise.all([...requests, excess]);
  assert.equal((await close).terminalObserved, true);
  assert.match(String(overload), /capacity/);
  assert.equal(observations, 64);
  await host.openProfile(profile());
  assert.equal((await read()).profileId, "p.1");
});

test("host queue capacity is global per owner, reserved slots remain bounded, and failures return slots", async () => {
  const locks = new Map();
  const release = defer();
  const calls = [];
  const errors = [];
  for (let index = 0; index < 64; index++) {
    calls.push(exclusive(locks, `p.${index}`, async () => { await release.promise; throw new Error("fixture"); }).catch(() => {}));
  }
  for (let index = 0; index < 8; index++) {
    calls.push(exclusive(locks, `settle.${index}`, () => release.promise, { settlement: true }));
  }
  const excess = [exclusive(locks, "extra", () => {}), exclusive(locks, "extra-settle", () => {}, { settlement: true })]
    .map((pending) => pending.catch((error) => { errors.push(error); }));
  await turn();
  const otherOwner = new Map();
  assert.equal(await exclusive(otherOwner, "other", () => 7), 7);
  release.resolve();
  await Promise.all([...calls, ...excess]);
  assert.equal(errors.length, 2);
  assert.ok(errors.every((error) => /capacity/.test(error.message)));
  assert.equal(locks.size, 0);
  assert.equal(await exclusive(locks, "reused", () => 8), 8);
});

test("same-profile FIFO ordering survives rejection without overlapping consumers", async () => {
  const locks = new Map();
  const events = [];
  const first = exclusive(locks, "p.1", async () => { events.push(1); await turn(); events.push(2); throw new Error("fixture"); }).catch(() => {});
  const second = exclusive(locks, "p.1", () => events.push(3), { settlement: true });
  await Promise.all([first, second]);
  assert.deepEqual(events, [1, 2, 3]);
  assert.equal(locks.size, 0);
});

test("snapshot retains unknown __proto__ action fields for exact-key rejection", async () => {
  const { host, calls } = fixture();
  await host.openProfile(profile());
  const request = operation();
  request.typedAction = JSON.parse(JSON.stringify(NAV).replace(/}$/, ',"__proto__":null}'));
  await assert.rejects(host.navigateOrAct(request), /unknown fields/);
  assert.equal(calls.filter(([kind]) => kind === "dispatch").length, 0);
});

test("snapshot refuses nested accessor code without reading it", async () => {
  const { host, calls } = fixture();
  await host.openProfile(profile());
  let reads = 0;
  const request = operation();
  Object.defineProperty(request.typedAction, "url", { enumerable: true, get() { reads++; return NAV.url; } });
  await assert.rejects(host.navigateOrAct(request), /data/);
  assert.equal(reads, 0);
  assert.equal(calls.filter(([kind]) => kind === "dispatch").length, 0);
});

test("input scalar and key budgets reject before retaining oversized data", async () => {
  const { host } = fixture();
  const request = profile();
  request.principalId = "x".repeat(1_048_577);
  await assert.rejects(host.openProfile(request));
  await host.openProfile(profile());
  const effect = operation();
  effect.typedAction["x".repeat(1_048_577)] = null;
  await assert.rejects(host.navigateOrAct(effect));
});

for (const method of ["navigateOrAct", "reconcileOperation"]) {
  test(`${method} reads a terminal persisted reconciliation instead of stale local unknown`, async () => {
    const { host, calls } = fixture();
    await host.openProfile(profile());
    await host.navigateOrAct(operation());
    const observed = await host.reconcilePersistedOperation(operation());
    assert.equal(observed.terminalObserved, true);
    const again = await host[method](operation());
    assert.equal(again.terminalObserved, true);
    assert.equal(again.semanticDigest, observed.semanticDigest);
    assert.equal(calls.filter(([kind]) => kind === "dispatch").length, 1);
    assert.equal(calls.filter(([kind]) => kind === "reconcile").length, 1);
    assert.equal((await host.closeProfile(identity())).terminalObserved, true);
  });
}

test("live and persisted reconciliation share one profile serialization domain", async () => {
  const entered = defer();
  const release = defer();
  let reconciliations = 0;
  const { host } = fixture({ async reconcile() {
    reconciliations++;
    entered.resolve();
    await release.promise;
    return { terminalObserved: true, status: "succeeded", outcomeDigest: D };
  } });
  await host.openProfile(profile());
  await host.navigateOrAct(operation());
  const live = host.reconcileOperation(operation());
  await entered.promise;
  const persisted = host.reconcilePersistedOperation(operation());
  try { await turn(); } finally { release.resolve(); }
  assert.ok((await Promise.all([live, persisted])).every((result) => result.terminalObserved));
  assert.equal(reconciliations, 1);
});

test("persisted recovery checks the original deadline identity without requiring it to be live", async () => {
  const { host, calls, setNow } = fixture();
  await host.openProfile(profile());
  await host.navigateOrAct(operation());
  setNow(20000);
  await assert.rejects(host.reconcilePersistedOperation({ ...operation(), deadlineMs: 9001 }), /immutable/);
  assert.equal(calls.filter(([kind]) => kind === "reconcile").length, 0);
  assert.equal((await host.reconcilePersistedOperation(operation())).terminalObserved, true);
});

test("snapshot must not erase an unknown own action key whose value is undefined", async () => {
  const { host } = fixture();
  await host.openProfile(profile());
  const request = operation();
  request.typedAction.unregistered = undefined;
  await assert.rejects(host.navigateOrAct(request), /unknown fields/);
});

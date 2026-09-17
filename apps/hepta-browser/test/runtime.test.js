import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { typedActionDigest } from "../src/actions.js";
import { FileBrowserOperationJournal } from "../src/journal.js";
import { BrowserProfileHost } from "../src/runtime.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
const D5 = "5".repeat(64);
const D6 = "6".repeat(64);
const D7 = "7".repeat(64);
const D8 = "8".repeat(64);
const ACTION = Object.freeze({ kind: "navigate", url: "https://example.com/next" });
const PAYLOAD = typedActionDigest(ACTION);

async function journal() {
  const dir = await mkdtemp(join(tmpdir(), "hepta-browser-test-"));
  return new FileBrowserOperationJournal(join(dir, "operations.json"));
}

function input(overrides = {}) {
  return {
    profileId: "profile.1",
    principalId: "principal.1",
    manifestDigest: D1,
    grantDigest: D2,
    generation: 1,
    expiresAtMs: 10_000,
    allowedOrigins: ["https://example.com"],
    effectGrants: [
      {
        grantDigest: D5,
        action: "navigate",
        destinationOrigin: "https://example.com",
        finalPayloadDigest: PAYLOAD,
        authorityEpoch: 7,
        expiresAtMs: 9_500,
      },
    ],
    ...overrides,
  };
}

function isolation() {
  return {
    processIsolationEnforced: true,
    profileIsolationEnforced: true,
    credentialIsolationEnforced: true,
    networkPolicyEnforced: true,
    sandboxDigest: D6,
    networkPolicyDigest: D7,
  };
}

function driver({
  terminalOnAct = false,
  terminalOnReconcile = true,
  actImpl,
  startImpl,
  observeOrigin = "https://example.com",
} = {}) {
  let actCalls = 0;
  let startCalls = 0;
  const value = {
    supportsAbort: true,
    async start(payload, options) {
      startCalls += 1;
      if (startImpl) return startImpl(payload, options);
      return { started: true, processId: `servo.process.${startCalls}`, isolation: isolation() };
    },
    async observe() {
      return {
        pageGeneration: 1,
        documentDigest: D3,
        origin: observeOrigin,
      };
    },
    async act(payload, options) {
      actCalls += 1;
      if (actImpl) return actImpl(payload, options);
      return terminalOnAct
        ? { terminalObserved: true, status: "succeeded", outcomeDigest: D1 }
        : { terminalObserved: false };
    },
    async reconcile() {
      return terminalOnReconcile
        ? { terminalObserved: true, status: "succeeded", outcomeDigest: D1 }
        : { terminalObserved: false };
    },
    async stop() {
      return { stopped: true };
    },
    async contain() {
      return { contained: true };
    },
    counts() {
      return { actCalls, startCalls };
    },
  };
  return value;
}

function authority({ deny = false, onVerify } = {}) {
  let calls = 0;
  return {
    async verifyFinalUse({ request, grant, verifiedUse }, { signal }) {
      calls += 1;
      onVerify?.({ request, grant, verifiedUse, signal });
      if (deny) return { authorized: false };
      return {
        authorized: true,
        authorityReceiptDigest: D8,
        revocationRevision: 11,
        grantDigest: request.effectGrantDigest,
        finalPayloadDigest: request.finalPayloadDigest,
        authorityEpoch: request.authorityEpoch,
        verifiedUseWitnessDigest: request.verifiedUseWitnessDigest,
      };
    },
    calls() {
      return calls;
    },
  };
}

function verifiedUse(overrides = {}) {
  return {
    witnessDigest: D6,
    grantDigest: D5,
    finalPayloadDigest: PAYLOAD,
    authorityEpoch: 7,
    expiresAtMs: 8_500,
    ...overrides,
  };
}

function operation(overrides = {}) {
  return {
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    operationId: "operation.1",
    pageGeneration: 1,
    action: "navigate",
    typedAction: ACTION,
    destinationOrigin: "https://example.com",
    finalPayloadDigest: PAYLOAD,
    effectGrantDigest: D5,
    authorityEpoch: 7,
    deadlineMs: 9_000,
    verifiedUse: verifiedUse(),
    ...overrides,
  };
}

async function readyHost({ driverValue = driver(), authorityValue = authority(), clock = () => 1_000, journalValue } = {}) {
  const journalInstance = journalValue ?? (await journal());
  const host = new BrowserProfileHost({
    driver: driverValue,
    authority: authorityValue,
    journal: journalInstance,
    clock,
  });
  const session = await host.openProfile(input());
  const page = await host.observePage({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    observationBudget: 2048,
  });
  return { host, session, page, journal: journalInstance };
}

test("opens, observes, reconciles indeterminate action, and closes", async () => {
  const { host, session, page } = await readyHost();
  assert.equal(session.effectGrantCount, 1);
  assert.equal(session.recoveredOutstandingOperations, 0);
  assert.equal(page.pageGeneration, 1);
  assert.equal(page.quarantined, false);
  const effect = await host.navigateOrAct(operation());
  assert.equal(effect.status, "indeterminate");
  await assert.rejects(
    host.closeProfile({ profileId: "profile.1", principalId: "principal.1", generation: 1 }),
    /requiring reconciliation/,
  );
  const terminal = await host.reconcileOperation({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    operationId: "operation.1",
  });
  assert.equal(terminal.status, "succeeded");
  assert.equal(terminal.terminalObserved, true);
  const replay = await host.navigateOrAct(operation());
  assert.equal(replay.semanticDigest, terminal.semanticDigest);
  const closed = await host.closeProfile({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
  });
  assert.equal(closed.terminalObserved, true);
});

test("concurrent duplicate operation is dispatched exactly once", async () => {
  let release;
  const blocked = new Promise((resolve) => {
    release = resolve;
  });
  let entered;
  const enteredPromise = new Promise((resolve) => {
    entered = resolve;
  });
  const d = driver({
    actImpl: async () => {
      entered();
      await blocked;
      return { terminalObserved: false };
    },
  });
  const { host } = await readyHost({ driverValue: d });
  const first = host.navigateOrAct(operation());
  await enteredPromise;
  const second = host.navigateOrAct(operation());
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(d.counts().actCalls, 1);
  release();
  const [left, right] = await Promise.all([first, second]);
  assert.equal(left.semanticDigest, right.semanticDigest);
  assert.equal(d.counts().actCalls, 1);
});

test("driver throw after possible effect becomes durable indeterminate and never redispatches", async () => {
  const d = driver({
    actImpl: async () => {
      throw new Error("socket disappeared after submit");
    },
  });
  const { host } = await readyHost({ driverValue: d });
  const first = await host.navigateOrAct(operation());
  assert.equal(first.status, "indeterminate");
  assert.equal(first.terminalObserved, false);
  const replay = await host.navigateOrAct(operation());
  assert.equal(replay.semanticDigest, first.semanticDigest);
  assert.equal(d.counts().actCalls, 1);
});

test("reconciliation and cleanup remain available after profile, grant, witness, and old deadline expiry", async () => {
  let now = 1_000;
  const { host } = await readyHost({ clock: () => now });
  const first = await host.navigateOrAct(operation());
  assert.equal(first.status, "indeterminate");
  now = 20_000;
  const terminal = await host.reconcileOperation({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    operationId: "operation.1",
    reconcileDeadlineMs: 20_500,
  });
  assert.equal(terminal.status, "succeeded");
  const closed = await host.closeProfile({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    closeDeadlineMs: 20_500,
  });
  assert.equal(closed.terminalObserved, true);
});

test("restart hydrates outstanding durable operation and reconciles without redispatch", async () => {
  const durable = await journal();
  const d1 = driver();
  const first = await readyHost({ driverValue: d1, journalValue: durable });
  const unknown = await first.host.navigateOrAct(operation());
  assert.equal(unknown.status, "indeterminate");
  assert.equal(d1.counts().actCalls, 1);

  const d2 = driver();
  const host2 = new BrowserProfileHost({
    driver: d2,
    authority: authority(),
    journal: durable,
    clock: () => 1_000,
  });
  const session2 = await host2.openProfile(input());
  assert.equal(session2.recoveredOutstandingOperations, 1);
  const terminal = await host2.reconcileOperation({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    operationId: "operation.1",
  });
  assert.equal(terminal.status, "succeeded");
  assert.equal(d2.counts().actCalls, 0);
  const replay = await host2.navigateOrAct(operation());
  assert.equal(replay.semanticDigest, terminal.semanticDigest);
  assert.equal(d2.counts().actCalls, 0);
});

test("typed payload, destination, effect grant and verified-use witness are all bound", async () => {
  const { host } = await readyHost();
  await assert.rejects(
    host.navigateOrAct(
      operation({ typedAction: { kind: "navigate", url: "https://example.com/other" } }),
    ),
    /final payload digest|destination origin/,
  );
  await assert.rejects(
    host.navigateOrAct(operation({ finalPayloadDigest: D3 })),
    /final payload digest/,
  );
  await assert.rejects(
    host.navigateOrAct(operation({ authorityEpoch: 8 })),
    /does not bind/,
  );
  await assert.rejects(
    host.navigateOrAct(
      operation({ verifiedUse: verifiedUse({ finalPayloadDigest: D3 }) }),
    ),
    /verified use witness/,
  );
});

test("final authority denial prevents durable effect dispatch", async () => {
  const auth = authority({ deny: true });
  const d = driver();
  const { host } = await readyHost({ driverValue: d, authorityValue: auth });
  await assert.rejects(host.navigateOrAct(operation()), /authority verification was denied/);
  assert.equal(auth.calls(), 1);
  assert.equal(d.counts().actCalls, 0);
});

test("replay rejects immutable semantic substitution without rerunning authority", async () => {
  const auth = authority();
  const d = driver({ terminalOnReconcile: false });
  const { host } = await readyHost({ driverValue: d, authorityValue: auth });
  const first = await host.navigateOrAct(operation());
  assert.equal(first.status, "indeterminate");
  assert.equal(auth.calls(), 1);
  for (const mutation of [
    { deadlineMs: 8_999 },
    { pageGeneration: 2 },
    { finalPayloadDigest: D3 },
    { authorityEpoch: 8 },
    { verifiedUse: verifiedUse({ witnessDigest: D7 }) },
  ]) {
    await assert.rejects(
      host.navigateOrAct(operation(mutation)),
      /changed semantics|does not bind|final payload digest/,
    );
  }
  assert.equal(d.counts().actCalls, 1);
  assert.equal(auth.calls(), 1);
});

test("concurrent open is serialized and starts only one worker", async () => {
  let release;
  let entered;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const enteredPromise = new Promise((resolve) => {
    entered = resolve;
  });
  const d = driver({
    startImpl: async () => {
      entered();
      await gate;
      return { started: true, processId: "servo.process.1", isolation: isolation() };
    },
  });
  const host = new BrowserProfileHost({
    driver: d,
    authority: authority(),
    journal: await journal(),
    clock: () => 1_000,
  });
  const first = host.openProfile(input());
  await enteredPromise;
  const second = host.openProfile(input());
  release();
  await first;
  await assert.rejects(second, /already open/);
  assert.equal(d.counts().startCalls, 1);
});

test("driver timeout becomes indeterminate and abort is signalled", async () => {
  let sawAbort = false;
  const d = driver({
    actImpl: async (_payload, { signal }) =>
      new Promise((_resolve, reject) => {
        signal.addEventListener(
          "abort",
          () => {
            sawAbort = true;
            reject(signal.reason);
          },
          { once: true },
        );
      }),
  });
  const now = Date.now();
  const grant = {
    grantDigest: D5,
    action: "navigate",
    destinationOrigin: "https://example.com",
    finalPayloadDigest: PAYLOAD,
    authorityEpoch: 7,
    expiresAtMs: now + 900,
  };
  const host = new BrowserProfileHost({
    driver: d,
    authority: authority(),
    journal: await journal(),
    clock: () => Date.now(),
  });
  await host.openProfile(input({ expiresAtMs: now + 1_000, effectGrants: [grant] }));
  await host.observePage({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    observationBudget: 128,
  });
  const result = await host.navigateOrAct(
    operation({
      deadlineMs: now + 50,
      verifiedUse: verifiedUse({ expiresAtMs: now + 800 }),
    }),
  );
  assert.equal(result.status, "indeterminate");
  assert.equal(sawAbort, true);
  assert.equal(d.counts().actCalls, 1);
});

test("out-of-scope observed origin quarantines profile and denies new effects", async () => {
  const d = driver({ observeOrigin: "https://outside.example" });
  const host = new BrowserProfileHost({
    driver: d,
    authority: authority(),
    journal: await journal(),
    clock: () => 1_000,
  });
  await host.openProfile(input());
  const page = await host.observePage({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    observationBudget: 128,
  });
  assert.equal(page.originAllowed, false);
  assert.equal(page.quarantined, true);
  await assert.rejects(host.navigateOrAct(operation()), /quarantined/);
});

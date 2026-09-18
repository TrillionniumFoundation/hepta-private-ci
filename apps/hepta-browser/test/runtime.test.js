import assert from "node:assert/strict";
import test from "node:test";

import { browserActionDigest } from "../src/action.js";
import { BrowserProfileHost } from "../src/runtime.js";
import { canonicalDigest } from "../src/runtime-contract.js";
import { MemoryBrowserOperationJournal } from "../src/journal.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
const D4 = "4".repeat(64);
const D5 = "5".repeat(64);
const W1 = "a".repeat(64);
const SEMANTIC = Object.freeze({
  controls: [],
  forms: [],
  links: [],
  schema: "hepta.browser.semantic-observation.v1",
  title: "Example",
  truncated: false,
  viewport: { height: 720, width: 1280 },
  visibleText: "hello",
});
const SEMANTIC_DIGEST = canonicalDigest(SEMANTIC);

function navigationAction(url = "https://example.com/path") {
  return Object.freeze({
    kind: "navigate",
    url,
    policyDigest: D1,
    expectedRevision: 7,
  });
}

const NAV = navigationAction();
const NAV_DIGEST = browserActionDigest(NAV);

function effectGrant(overrides = {}) {
  return {
    grantDigest: D5,
    action: "navigate",
    destinationOrigin: "https://example.com",
    finalPayloadDigest: NAV_DIGEST,
    authorityEpoch: 7,
    expiresAtMs: 9_500,
    ...overrides,
  };
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
    effectGrants: [effectGrant()],
    ...overrides,
  };
}

function authority({ authorized = true, witnessDigest = W1, delay = 0 } = {}) {
  let calls = 0;
  return {
    get calls() {
      return calls;
    },
    async withVerifiedUse(request, consumer) {
      calls += 1;
      if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
      if (!authorized) throw new TypeError("final-use authority was denied");
      return consumer({
        authorized: true,
        witnessDigest,
        authorityEpoch: request.authorityEpoch,
        requestDigest: request.requestDigest,
      });
    },
  };
}

function driver({ terminalOnReconcile = true, dispatchImpl, observeImpl } = {}) {
  let dispatchCalls = 0;
  let containCalls = 0;
  let stopCalls = 0;
  return {
    supportsAbort: true,
    get actCalls() {
      return dispatchCalls;
    },
    get dispatchCalls() {
      return dispatchCalls;
    },
    get containCalls() {
      return containCalls;
    },
    get stopCalls() {
      return stopCalls;
    },
    async start() {
      return {
        started: true,
        processId: "servo.process.1",
        profileOwnerDigest: D4,
      };
    },
    async observe(payload) {
      if (observeImpl) return observeImpl(payload);
      return {
        pageGeneration: 1,
        documentDigest: D3,
        semanticDigest: SEMANTIC_DIGEST,
        semanticObservation: SEMANTIC,
        origin: "https://example.com",
      };
    },
    async dispatch(semantics, context) {
      dispatchCalls += 1;
      if (dispatchImpl) return dispatchImpl(semantics, context);
      return { terminalObserved: false };
    },
    async reconcile() {
      return terminalOnReconcile
        ? { terminalObserved: true, status: "succeeded", outcomeDigest: D1 }
        : { terminalObserved: false };
    },
    async contain() {
      containCalls += 1;
      return { contained: true };
    },
    async stop() {
      stopCalls += 1;
      return { stopped: true };
    },
  };
}

function operation(overrides = {}) {
  return {
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    operationId: "operation.1",
    pageGeneration: 1,
    typedAction: NAV,
    destinationOrigin: "https://example.com",
    finalPayloadDigest: NAV_DIGEST,
    effectGrantDigest: D5,
    authorityEpoch: 7,
    deadlineMs: 9_000,
    ...overrides,
  };
}

async function preparedHost(options = {}) {
  const fakeDriver = options.driver ?? driver();
  const finalAuthority = options.authority ?? authority();
  const clock = options.clock ?? (() => 1_000);
  const journal = options.journal ?? new MemoryBrowserOperationJournal();
  const host = new BrowserProfileHost({
    driver: fakeDriver,
    authority: finalAuthority,
    journal,
    clock,
    allowVolatileJournalForTests: true,
    driverCallTimeoutMs: options.driverCallTimeoutMs ?? 50,
  });
  const session = await host.openProfile(options.profileInput ?? input());
  const page = await host.observePage({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    observationBudget: options.observationBudget ?? 2048,
  });
  return { host, fakeDriver, finalAuthority, journal, session, page };
}

test("effect owner rejects volatile journals unless a test explicitly opts in", () => {
  assert.throws(
    () =>
      new BrowserProfileHost({
        driver: driver(),
        authority: authority(),
        journal: new MemoryBrowserOperationJournal(),
        clock: () => 1_000,
        driverCallTimeoutMs: 50,
      }),
    /requires a durable operation journal/,
  );
});

test("global active profile capacity rejects a second worker before start", async () => {
  const fakeDriver = driver();
  let starts = 0;
  const originalStart = fakeDriver.start.bind(fakeDriver);
  fakeDriver.start = async (...args) => {
    starts += 1;
    return originalStart(...args);
  };
  const host = new BrowserProfileHost({
    driver: fakeDriver,
    authority: authority(),
    journal: new MemoryBrowserOperationJournal(),
    clock: () => 1_000,
    allowVolatileJournalForTests: true,
    driverCallTimeoutMs: 50,
    maxActiveProfiles: 1,
  });
  await host.openProfile(input());
  await assert.rejects(
    host.openProfile(
      input({
        profileId: "profile.2",
        principalId: "principal.2",
      }),
    ),
    (error) =>
      error?.name === "BrowserBackpressureError" &&
      error?.code === "BROWSER_PROFILE_CAPACITY",
  );
  assert.equal(starts, 1);
});

test("opens, publishes bounded semantic observation, reconciles, retires journal, and closes", async () => {
  const { host, journal, session, page } = await preparedHost();
  assert.equal(session.profileOwnerDigest, D4);
  assert.equal(page.semanticDigest, SEMANTIC_DIGEST);
  assert.deepEqual(page.semanticObservation, SEMANTIC);
  const effect = await host.navigateOrAct(operation());
  assert.equal(effect.status, "indeterminate");
  await assert.rejects(
    host.closeProfile({ profileId: "profile.1", principalId: "principal.1", generation: 1 }),
    /requiring reconciliation/,
  );
  const terminal = await host.reconcileOperation(operation());
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
  assert.deepEqual(await journal.listOperations("profile.1", 1), []);
  await assert.rejects(
    journal.assertProfileGenerationAvailable("profile.1", 1),
    /already been retired/,
  );
  await journal.assertProfileGenerationAvailable("profile.1", 2);
  await assert.rejects(host.openProfile(input()), /already been retired/);
});

test("semantic observation digest and budget fail closed", async () => {
  const badDigest = driver({
    observeImpl: async () => ({
      pageGeneration: 1,
      documentDigest: D3,
      semanticDigest: D1,
      semanticObservation: SEMANTIC,
      origin: "https://example.com",
    }),
  });
  const host = new BrowserProfileHost({
    driver: badDigest,
    authority: authority(),
    journal: new MemoryBrowserOperationJournal(),
    clock: () => 1_000,
    allowVolatileJournalForTests: true,
    driverCallTimeoutMs: 50,
  });
  await host.openProfile(input());
  await assert.rejects(
    host.observePage({
      profileId: "profile.1",
      principalId: "principal.1",
      generation: 1,
      observationBudget: 2048,
    }),
    /semantic observation digest mismatch/,
  );
});

test("same operation is single-flight and never double-dispatches", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const fakeDriver = driver({
    dispatchImpl: async () => {
      await gate;
      return { terminalObserved: false };
    },
  });
  const { host, finalAuthority } = await preparedHost({ driver: fakeDriver });
  const first = host.navigateOrAct(operation());
  const second = host.navigateOrAct(operation());
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(fakeDriver.dispatchCalls, 1);
  assert.equal(finalAuthority.calls, 1);
  release();
  const [left, right] = await Promise.all([first, second]);
  assert.equal(fakeDriver.dispatchCalls, 1);
  assert.equal(left.semanticDigest, right.semanticDigest);
});

test("one-WebView driver ceiling blocks another effect while the prior one is unknown", async () => {
  let pageGeneration = 0;
  const fakeDriver = driver({
    terminalOnReconcile: false,
    observeImpl: async () => ({
      pageGeneration: ++pageGeneration,
      documentDigest: D3,
      semanticDigest: SEMANTIC_DIGEST,
      semanticObservation: SEMANTIC,
      origin: "https://example.com",
    }),
  });
  fakeDriver.maxOutstandingOperations = 1;
  const { host } = await preparedHost({ driver: fakeDriver });
  const first = await host.navigateOrAct(operation());
  assert.equal(first.status, "indeterminate");
  const refreshed = await host.observePage({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    observationBudget: 2048,
  });
  assert.equal(refreshed.pageGeneration, 2);
  await assert.rejects(
    host.navigateOrAct(
      operation({ operationId: "operation.2", pageGeneration: 2 }),
    ),
    /profile operation capacity is exhausted/,
  );
  assert.equal(fakeDriver.dispatchCalls, 1);
});

test("driver throw after dispatch boundary becomes indeterminate and retry never redispatches", async () => {
  const fakeDriver = driver({
    dispatchImpl: async () => {
      throw new Error("connection lost after submit");
    },
  });
  const { host } = await preparedHost({ driver: fakeDriver });
  const first = await host.navigateOrAct(operation());
  assert.equal(first.status, "indeterminate");
  assert.equal(first.observationReason, "driver_error_after_dispatch_boundary");
  const replay = await host.navigateOrAct(operation());
  assert.equal(replay.semanticDigest, first.semanticDigest);
  assert.equal(fakeDriver.dispatchCalls, 1);
});

test("worker pre-dispatch rejection is terminal and is never mislabeled as crossed", async () => {
  const rejected = Object.assign(
    new Error("worker rejected stale page snapshot before admission"),
    {
      name: "BrowserWorkerPreDispatchError",
      code: "BROWSER_WORKER_PRE_DISPATCH_REJECTED",
      outcomeDigest: D4,
    },
  );
  const fakeDriver = driver({
    dispatchImpl: async () => {
      throw rejected;
    },
  });
  const { host, journal } = await preparedHost({ driver: fakeDriver });
  const result = await host.navigateOrAct(operation());
  assert.equal(result.status, "failed");
  assert.equal(result.terminalObserved, true);
  assert.equal(result.observationReason, "worker_rejected_before_dispatch");
  assert.equal(result.outcomeDigest, D4);
  const durable = await journal.getOperation("profile.1", 1, "operation.1");
  assert.equal(durable.receipt.status, "failed");
  assert.equal(durable.receipt.terminalObserved, true);
  assert.equal(fakeDriver.dispatchCalls, 1);
});

test("reconciliation and cleanup remain available after grant and deadline expiry", async () => {
  let now = 1_000;
  const { host } = await preparedHost({ clock: () => now });
  const first = await host.navigateOrAct(operation());
  assert.equal(first.status, "indeterminate");
  now = 20_000;
  await assert.rejects(
    host.navigateOrAct(operation({ operationId: "operation.new" })),
    /profile grant has expired/,
  );
  const terminal = await host.reconcileOperation(operation());
  assert.equal(terminal.status, "succeeded");
  const closed = await host.closeProfile({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
  });
  assert.equal(closed.terminalObserved, true);
});

test("typed action bytes are bound to final payload digest and destination", async () => {
  const { host, fakeDriver } = await preparedHost();
  await assert.rejects(
    host.navigateOrAct(operation({ typedAction: navigationAction("https://example.com/other") })),
    /does not bind typedAction/,
  );
  const evil = navigationAction("https://other.example/path");
  await assert.rejects(
    host.navigateOrAct(operation({ typedAction: evil, finalPayloadDigest: browserActionDigest(evil) })),
    /does not match destinationOrigin/,
  );
  assert.equal(fakeDriver.dispatchCalls, 0);
});

test("final-use authority denial cannot reach the driver", async () => {
  const denied = authority({ authorized: false });
  const { host, fakeDriver } = await preparedHost({ authority: denied });
  await assert.rejects(host.navigateOrAct(operation()), /final-use authority was denied/);
  assert.equal(denied.calls, 1);
  assert.equal(fakeDriver.dispatchCalls, 0);
});

test("durable intent and local dispatch occur inside the final-use fence", async () => {
  let insideFence = false;
  const baseJournal = new MemoryBrowserOperationJournal();
  const journal = {
    async assertProfileGenerationAvailable(...args) {
      return baseJournal.assertProfileGenerationAvailable(...args);
    },
    async recordDispatch(record) {
      assert.equal(insideFence, true);
      return baseJournal.recordDispatch(record);
    },
    async recordObservation(record) {
      return baseJournal.recordObservation(record);
    },
    async getOperation(...args) {
      return baseJournal.getOperation(...args);
    },
    async listOperations(...args) {
      return baseJournal.listOperations(...args);
    },
    async retireProfile(...args) {
      return baseJournal.retireProfile(...args);
    },
  };
  const finalAuthority = {
    async withVerifiedUse(request, consumer) {
      insideFence = true;
      try {
        return await consumer({
          authorized: true,
          witnessDigest: W1,
          authorityEpoch: request.authorityEpoch,
          requestDigest: request.requestDigest,
        });
      } finally {
        insideFence = false;
      }
    },
  };
  const fakeDriver = driver({
    dispatchImpl: async () => {
      assert.equal(insideFence, true);
      return { terminalObserved: false };
    },
  });
  const { host } = await preparedHost({ driver: fakeDriver, authority: finalAuthority, journal });
  await host.navigateOrAct(operation());
  assert.equal(insideFence, false);
});

test("generic type text never enters the durable operation journal", async () => {
  const secret = "p@ssword-do-not-persist";
  const typedAction = Object.freeze({ kind: "type", selector: "#password", text: secret });
  const typedDigest = browserActionDigest(typedAction);
  const grant = effectGrant({
    action: "type",
    finalPayloadDigest: typedDigest,
  });
  const journal = new MemoryBrowserOperationJournal();
  const { host } = await preparedHost({
    journal,
    profileInput: input({ effectGrants: [grant] }),
  });
  await host.navigateOrAct(operation({
    operationId: "operation.type",
    typedAction,
    finalPayloadDigest: typedDigest,
  }));
  const durable = await journal.getOperation("profile.1", 1, "operation.type");
  assert.equal(JSON.stringify(durable).includes(secret), false);
  assert.equal("typedAction" in durable, false);
  assert.equal(durable.finalPayloadDigest, typedDigest);
});

test("profile serialization prevents close racing an in-flight effect", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const fakeDriver = driver({
    dispatchImpl: async () => {
      await gate;
      return { terminalObserved: false };
    },
  });
  const { host } = await preparedHost({ driver: fakeDriver });
  const effect = host.navigateOrAct(operation());
  const close = host.closeProfile({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
  });
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(fakeDriver.stopCalls, 0);
  release();
  await effect;
  await assert.rejects(close, /requiring reconciliation/);
  assert.equal(fakeDriver.stopCalls, 0);
});

test("driver timeout aborts dispatch, waits for abort settlement, and preserves an indeterminate operation", async () => {
  let aborted = false;
  const fakeDriver = driver({
    dispatchImpl: async (_semantics, { signal }) =>
      new Promise((_resolve, reject) => {
        signal.addEventListener(
          "abort",
          () => {
            aborted = true;
            reject(signal.reason);
          },
          { once: true },
        );
      }),
  });
  const { host } = await preparedHost({ driver: fakeDriver, driverCallTimeoutMs: 10 });
  const first = await host.navigateOrAct(operation());
  assert.equal(first.status, "indeterminate");
  assert.equal(first.observationReason, "driver_timeout");
  assert.equal(aborted, true);
  const replay = await host.navigateOrAct(operation());
  assert.equal(replay.semanticDigest, first.semanticDigest);
  assert.equal(fakeDriver.dispatchCalls, 1);
});

test("delayed final-use authority cannot enter the effect boundary after Browser deadline", async () => {
  let now = 1_000;
  const fakeDriver = driver();
  const delayedAuthority = {
    async withVerifiedUse(request, consumer) {
      now = request.deadlineMs + 1;
      return consumer({
        authorized: true,
        witnessDigest: W1,
        authorityEpoch: request.authorityEpoch,
        requestDigest: request.requestDigest,
      });
    },
  };
  const host = new BrowserProfileHost({
    driver: fakeDriver,
    authority: delayedAuthority,
    journal: new MemoryBrowserOperationJournal(),
    clock: () => now,
    allowVolatileJournalForTests: true,
    driverCallTimeoutMs: 50,
  });
  await host.openProfile(input());
  await host.observePage({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    observationBudget: 2048,
  });
  await assert.rejects(
    host.navigateOrAct(operation({ deadlineMs: 1_100 })),
    /deadlineMs has expired/,
  );
  assert.equal(fakeDriver.dispatchCalls, 0);
});

test("replay rejects immutable semantic substitution", async () => {
  const { host } = await preparedHost({ driver: driver({ terminalOnReconcile: false }) });
  await host.navigateOrAct(operation());
  const changed = navigationAction("https://example.com/changed");
  await assert.rejects(
    host.navigateOrAct(operation({
      typedAction: changed,
      finalPayloadDigest: browserActionDigest(changed),
    })),
    /changed semantics|does not bind/,
  );
});

test("disallowed observed origin is quarantined and cannot authorize an action", async () => {
  const fakeDriver = driver({
    observeImpl: async () => ({
      pageGeneration: 1,
      documentDigest: D3,
      semanticDigest: SEMANTIC_DIGEST,
      semanticObservation: SEMANTIC,
      origin: "https://other.example",
    }),
  });
  const finalAuthority = authority();
  const host = new BrowserProfileHost({
    driver: fakeDriver,
    authority: finalAuthority,
    journal: new MemoryBrowserOperationJournal(),
    clock: () => 1_000,
    allowVolatileJournalForTests: true,
    driverCallTimeoutMs: 50,
  });
  await host.openProfile(input());
  const page = await host.observePage({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    observationBudget: 2048,
  });
  assert.equal(page.originAllowed, false);
  assert.equal(page.quarantined, true);
  assert.equal(fakeDriver.containCalls, 1);
  await assert.rejects(host.navigateOrAct(operation()), /profile is quarantined/);
  assert.equal(fakeDriver.dispatchCalls, 0);
});

test("persisted indeterminate operation reconciles after host process loss without redispatch", async () => {
  const journal = new MemoryBrowserOperationJournal();
  const firstDriver = driver({
    dispatchImpl: async () => {
      throw new Error("process lost after submit");
    },
  });
  const first = await preparedHost({ driver: firstDriver, journal });
  const unknown = await first.host.navigateOrAct(operation());
  assert.equal(unknown.status, "indeterminate");
  assert.equal(firstDriver.dispatchCalls, 1);

  const secondDriver = driver();
  const blockedHost = new BrowserProfileHost({
    driver: secondDriver,
    authority: authority(),
    journal,
    clock: () => 1_000,
    allowVolatileJournalForTests: true,
    driverCallTimeoutMs: 50,
  });
  await assert.rejects(
    blockedHost.openProfile(input()),
    /durable operation history/,
  );
  await assert.rejects(
    blockedHost.openProfile(input({ generation: 2 })),
    /unresolved durable effects/,
  );

  const recoveredHost = new BrowserProfileHost({
    driver: secondDriver,
    authority: authority(),
    journal,
    clock: () => 20_000,
    allowVolatileJournalForTests: true,
    driverCallTimeoutMs: 50,
  });
  const recovered = await recoveredHost.reconcilePersistedOperation(operation());
  assert.equal(recovered.status, "succeeded");
  assert.equal(recovered.terminalObserved, true);
  assert.equal(secondDriver.dispatchCalls, 0);
  assert.deepEqual(await journal.listOperations("profile.1", 1), []);
  await assert.rejects(
    journal.assertProfileGenerationAvailable("profile.1", 1),
    /already been retired/,
  );
  await journal.assertProfileGenerationAvailable("profile.1", 2);
});

test("terminal operation retention uses durable tombstones instead of exhausting active capacity", async () => {
  let pageGeneration = 0;
  const fakeDriver = driver({
    observeImpl: async () => ({
      pageGeneration: ++pageGeneration,
      documentDigest: D3,
      semanticDigest: SEMANTIC_DIGEST,
      semanticObservation: SEMANTIC,
      origin: "https://example.com",
    }),
    dispatchImpl: async () => ({
      terminalObserved: true,
      status: "succeeded",
      outcomeDigest: D1,
    }),
  });
  const { host } = await preparedHost({ driver: fakeDriver });
  for (let index = 0; index < 300; index += 1) {
    const receipt = await host.navigateOrAct(
      operation({
        operationId: `operation.${index}`,
        pageGeneration: index + 1,
      }),
    );
    assert.equal(receipt.terminalObserved, true);
    if (index < 299) {
      const refreshed = await host.observePage({
        profileId: "profile.1",
        principalId: "principal.1",
        generation: 1,
        observationBudget: 2048,
      });
      assert.equal(refreshed.pageGeneration, index + 2);
    }
  }
  assert.equal(fakeDriver.dispatchCalls, 300);
  const replay = await host.navigateOrAct(operation({ operationId: "operation.0" }));
  assert.equal(replay.terminalObserved, true);
  assert.equal(fakeDriver.dispatchCalls, 300);
});

test("effect grants can be admitted after profile open without widening final-use authority", async () => {
  const fakeDriver = driver();
  const host = new BrowserProfileHost({
    driver: fakeDriver,
    authority: authority(),
    journal: new MemoryBrowserOperationJournal(),
    clock: () => 1_000,
    allowVolatileJournalForTests: true,
    driverCallTimeoutMs: 50,
  });
  await host.openProfile(input({ effectGrants: [] }));
  const admitted = await host.admitEffectGrant({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    effectGrant: effectGrant(),
  });
  assert.equal(admitted.effectGrantCount, 1);
  await host.observePage({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    observationBudget: 2048,
  });
  const result = await host.navigateOrAct(operation());
  assert.equal(result.status, "indeterminate");
});

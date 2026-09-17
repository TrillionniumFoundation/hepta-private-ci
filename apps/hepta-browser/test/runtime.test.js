import assert from "node:assert/strict";
import test from "node:test";

import { BrowserProfileHost, browserTypedActionDigest } from "../src/runtime.js";
import { FileBrowserStateStore, MemoryBrowserStateStore } from "../src/state-store.js";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
const D5 = "5".repeat(64);
const ACTION = Object.freeze({ kind: "navigate", url: "https://example.com/path" });
const ACTION_DIGEST = browserTypedActionDigest(ACTION);

function profileInput(overrides = {}) {
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
        finalPayloadDigest: ACTION_DIGEST,
        authorityEpoch: 7,
        expiresAtMs: 9_500,
      },
    ],
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
    finalPayloadDigest: ACTION_DIGEST,
    effectGrantDigest: D5,
    authorityEpoch: 7,
    deadlineMs: 9_000,
    ...overrides,
  };
}

function driver(overrides = {}) {
  return {
    capabilities: {
      abortSignal: true,
      isolatedProcess: true,
      privateControlChannel: true,
      networkPolicyEnforced: true,
      profileIsolationEnforced: true,
      credentialBoundaryEnforced: true,
    },
    async start() {
      return { started: true, processId: "servo.process.1" };
    },
    async observe() {
      return {
        pageGeneration: 1,
        documentDigest: D3,
        origin: "https://example.com",
      };
    },
    async act() {
      return { terminalObserved: false };
    },
    async reconcile() {
      return { terminalObserved: true, status: "succeeded", outcomeDigest: D1 };
    },
    async stop() {
      return { stopped: true };
    },
    ...overrides,
  };
}

function authority() {
  const state = { revoked: false, claims: 0, deliveries: 0 };
  return {
    state,
    async claim(binding) {
      state.claims += 1;
      if (state.revoked) throw new Error("revoked");
      return { binding };
    },
    async withVerifiedUse(token, binding, consumer) {
      assert.deepEqual(token.binding, binding);
      if (state.revoked) throw new Error("revoked");
      state.deliveries += 1;
      return consumer();
    },
  };
}

async function openedHost({
  browserDriver = driver(),
  finalAuthority = authority(),
  store = new MemoryBrowserStateStore(),
  clock = () => 1_000,
} = {}) {
  const host = new BrowserProfileHost({
    driver: browserDriver,
    authority: finalAuthority,
    store,
    clock,
    allowVolatileStore: store.durable !== true,
  });
  await host.openProfile(profileInput());
  await host.observePage({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    observationBudget: 2048,
  });
  return { host, finalAuthority, store };
}

test("opens, observes, reconciles indeterminate action, and closes", async () => {
  const { host } = await openedHost();
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
    semanticDigest: effect.semanticDigest,
  });
  assert.equal(terminal.status, "succeeded");
  const replay = await host.navigateOrAct(operation());
  assert.equal(replay.semanticDigest, terminal.semanticDigest);
  const closed = await host.closeProfile({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
  });
  assert.equal(closed.terminalObserved, true);
});

test("same operation is single-flight across concurrent callers", async () => {
  let actCount = 0;
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const browserDriver = driver({
    async act() {
      actCount += 1;
      await gate;
      return { terminalObserved: true, status: "succeeded", outcomeDigest: D1 };
    },
  });
  const { host } = await openedHost({ browserDriver });
  const first = host.navigateOrAct(operation());
  const second = host.navigateOrAct(operation());
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(actCount, 1);
  release();
  const [left, right] = await Promise.all([first, second]);
  assert.equal(actCount, 1);
  assert.equal(left.semanticDigest, right.semanticDigest);
  assert.equal(left.status, "succeeded");
});

test("driver throw after effect boundary becomes indeterminate and never redispatches", async () => {
  let actCount = 0;
  const browserDriver = driver({
    async act() {
      actCount += 1;
      throw new Error("transport lost after submit");
    },
  });
  const { host } = await openedHost({ browserDriver });
  const first = await host.navigateOrAct(operation());
  assert.equal(first.status, "indeterminate");
  const replay = await host.navigateOrAct(operation());
  assert.equal(replay.status, "indeterminate");
  assert.equal(actCount, 1);
  const terminal = await host.reconcileOperation({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    operationId: "operation.1",
    semanticDigest: first.semanticDigest,
  });
  assert.equal(terminal.status, "succeeded");
});

test("reconciliation remains available after profile grant, effect grant, and operation deadline expire", async () => {
  let now = 1_000;
  const { host } = await openedHost({ clock: () => now });
  const effect = await host.navigateOrAct(operation());
  now = 20_000;
  const terminal = await host.reconcileOperation({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    operationId: "operation.1",
    semanticDigest: effect.semanticDigest,
    deadlineMs: 21_000,
  });
  assert.equal(terminal.status, "succeeded");
  await host.closeProfile({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    deadlineMs: 21_000,
  });
});

test("final-use revocation prevents effect dispatch and does not create an indeterminate operation", async () => {
  let actCount = 0;
  const finalAuthority = authority();
  finalAuthority.state.revoked = true;
  const { host } = await openedHost({
    finalAuthority,
    browserDriver: driver({ async act() { actCount += 1; return { terminalObserved: false }; } }),
  });
  await assert.rejects(host.navigateOrAct(operation()), /revoked/);
  assert.equal(actCount, 0);
  finalAuthority.state.revoked = false;
  const effect = await host.navigateOrAct(operation());
  assert.equal(effect.status, "indeterminate");
  assert.equal(actCount, 1);
});

test("typed action bytes are bound to final payload digest", async () => {
  const { host } = await openedHost();
  await assert.rejects(
    host.navigateOrAct(operation({ typedAction: { kind: "navigate", url: "https://example.com/other" } })),
    /finalPayloadDigest does not bind typedAction/,
  );
  await assert.rejects(
    host.navigateOrAct(operation({ destinationOrigin: "https://other.example" })),
    /outside the profile grant/,
  );
});

test("driver timeout becomes indeterminate and does not permit replay", async () => {
  let actCount = 0;
  const browserDriver = driver({
    async act({ signal }) {
      actCount += 1;
      return new Promise((_, reject) => {
        signal.addEventListener("abort", () => reject(signal.reason), { once: true });
      });
    },
  });
  const finalAuthority = authority();
  const store = new MemoryBrowserStateStore();
  const host = new BrowserProfileHost({
    driver: browserDriver,
    authority: finalAuthority,
    store,
    allowVolatileStore: true,
    clock: () => Date.now(),
    defaultDriverTimeoutMs: 20,
  });
  const expires = Date.now() + 5_000;
  await host.openProfile(profileInput({
    expiresAtMs: expires,
    effectGrants: [{
      grantDigest: D5,
      action: "navigate",
      destinationOrigin: "https://example.com",
      finalPayloadDigest: ACTION_DIGEST,
      authorityEpoch: 7,
      expiresAtMs: expires - 100,
    }],
  }));
  await host.observePage({
    profileId: "profile.1", principalId: "principal.1", generation: 1, observationBudget: 128,
  });
  const operationDeadline = Date.now() + 100;
  const effect = await host.navigateOrAct(operation({ deadlineMs: operationDeadline }));
  assert.equal(effect.status, "indeterminate");
  const replay = await host.navigateOrAct(operation({ deadlineMs: operationDeadline }));
  assert.equal(replay.status, "indeterminate");
  assert.equal(actCount, 1);
});

test("durable profile state survives host recreation for reconciliation", async () => {
  const directory = mkdtempSync(join(tmpdir(), "hepta-browser-state-"));
  const statePath = join(directory, "browser-state.json");
  const browserDriver = driver();
  const finalAuthority = authority();
  const firstStore = new FileBrowserStateStore({ path: statePath });
  const first = await openedHost({ browserDriver, finalAuthority, store: firstStore });
  const unknown = await first.host.navigateOrAct(operation());

  const secondStore = new FileBrowserStateStore({ path: statePath });
  const second = new BrowserProfileHost({
    driver: browserDriver,
    authority: finalAuthority,
    store: secondStore,
    clock: () => 20_000,
  });
  const recoverable = await second.listRecoverableProfiles();
  assert.equal(recoverable.length, 1);
  await second.recoverProfile({
    profileId: "profile.1", principalId: "principal.1", generation: 1,
  });
  const terminal = await second.reconcileOperation({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    operationId: "operation.1",
    semanticDigest: unknown.semanticDigest,
    deadlineMs: 21_000,
  });
  assert.equal(terminal.status, "succeeded");
});

test("concurrent open is serialized before process start", async () => {
  let startCount = 0;
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const browserDriver = driver({
    async start() {
      startCount += 1;
      await gate;
      return { started: true, processId: "servo.process.1" };
    },
  });
  const host = new BrowserProfileHost({
    driver: browserDriver,
    authority: authority(),
    store: new MemoryBrowserStateStore(),
    allowVolatileStore: true,
    clock: () => 1_000,
  });
  const first = host.openProfile(profileInput());
  const second = host.openProfile(profileInput());
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(startCount, 1);
  release();
  await first;
  await assert.rejects(second, /already open/);
  assert.equal(startCount, 1);
});

test("ungranted observed origin quarantines the profile", async () => {
  const browserDriver = driver({
    async observe() {
      return { pageGeneration: 1, documentDigest: D3, origin: "https://evil.example" };
    },
  });
  const host = new BrowserProfileHost({
    driver: browserDriver,
    authority: authority(),
    store: new MemoryBrowserStateStore(),
    allowVolatileStore: true,
    clock: () => 1_000,
  });
  await host.openProfile(profileInput());
  await assert.rejects(host.observePage({
    profileId: "profile.1", principalId: "principal.1", generation: 1, observationBudget: 128,
  }), /profile quarantined/);
  await assert.rejects(host.observePage({
    profileId: "profile.1", principalId: "principal.1", generation: 1, observationBudget: 128,
  }), /not active: quarantined/);
});

test("terminal operation can be compacted without reopening replay", async () => {
  const { host } = await openedHost({
    browserDriver: driver({
      async act() {
        return { terminalObserved: true, status: "succeeded", outcomeDigest: D1 };
      },
    }),
  });
  const terminal = await host.navigateOrAct(operation());
  const acknowledged = await host.acknowledgeTerminalOperation({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    operationId: "operation.1",
    semanticDigest: terminal.semanticDigest,
  });
  assert.equal(acknowledged.status, "succeeded");
  const replay = await host.navigateOrAct(operation());
  assert.equal(replay.status, "succeeded");
  await assert.rejects(
    host.navigateOrAct(operation({ typedAction: { kind: "navigate", url: "https://example.com/other" } })),
    /finalPayloadDigest does not bind typedAction|changed semantics/,
  );
});

test("operation intent is persisted before entering the driver effect boundary", async () => {
  const store = new MemoryBrowserStateStore();
  let observedPersistedIntent = false;
  const browserDriver = driver({
    async act() {
      const record = await store.loadProfile("profile.1");
      const entry = record.operations.find((candidate) => candidate.operationId === "operation.1");
      observedPersistedIntent = entry?.phase === "dispatching"
        && entry?.receipt?.status === "indeterminate";
      return { terminalObserved: false };
    },
  });
  const { host } = await openedHost({ browserDriver, store });
  await host.navigateOrAct(operation());
  assert.equal(observedPersistedIntent, true);
});

test("revocation between claim and final use blocks dispatch", async () => {
  let actCount = 0;
  const state = { claims: 0 };
  const finalAuthority = {
    async claim(binding) {
      state.claims += 1;
      return { binding };
    },
    async withVerifiedUse() {
      throw new Error("revoked after claim");
    },
  };
  const { host } = await openedHost({
    finalAuthority,
    browserDriver: driver({
      async act() {
        actCount += 1;
        return { terminalObserved: false };
      },
    }),
  });
  await assert.rejects(host.navigateOrAct(operation()), /revoked after claim/);
  assert.equal(state.claims, 1);
  assert.equal(actCount, 0);
});

test("profile or effect grant expiry during final-use claim blocks dispatch", async () => {
  let now = 1_000;
  let actCount = 0;
  const finalAuthority = {
    async claim(binding) {
      now = 9_600;
      return { binding };
    },
    async withVerifiedUse(token, binding, consumer) {
      assert.deepEqual(token.binding, binding);
      return consumer();
    },
  };
  const { host } = await openedHost({
    clock: () => now,
    finalAuthority,
    browserDriver: driver({
      async act() {
        actCount += 1;
        return { terminalObserved: false };
      },
    }),
  });
  await assert.rejects(host.navigateOrAct(operation()), /expired before final dispatch/);
  assert.equal(actCount, 0);
});

test("rejects stale page, unregistered grant, grant drift and authority-epoch drift", async () => {
  const { host } = await openedHost();
  await assert.rejects(host.navigateOrAct(operation({ pageGeneration: 2 })), /stale page generation/);
  await assert.rejects(host.navigateOrAct(operation({ effectGrantDigest: D2 })), /not registered/);
  await assert.rejects(
    host.navigateOrAct(operation({ finalPayloadDigest: D3 })),
    /finalPayloadDigest does not bind typedAction/,
  );
  await assert.rejects(host.navigateOrAct(operation({ authorityEpoch: 8 })), /does not bind/);
});

test("replay rejects every immutable semantic substitution without redispatch", async () => {
  let actCount = 0;
  const { host } = await openedHost({
    browserDriver: driver({
      async act() {
        actCount += 1;
        return { terminalObserved: false };
      },
    }),
  });
  const first = await host.navigateOrAct(operation());
  assert.equal(first.status, "indeterminate");
  for (const mutation of [
    { deadlineMs: 8_999 },
    { authorityEpoch: 8 },
    { pageGeneration: 2 },
  ]) {
    await assert.rejects(
      host.navigateOrAct(operation(mutation)),
      /changed semantics|does not bind|stale page generation/,
    );
  }
  assert.equal(actCount, 1);
});

test("same-page typed actions bind observed origin and exact payload bytes", async () => {
  const click = { kind: "click", selector: "#submit", button: "primary" };
  const clickDigest = browserTypedActionDigest(click);
  const clickGrant = {
    grantDigest: D5,
    action: "click",
    destinationOrigin: "https://example.com",
    finalPayloadDigest: clickDigest,
    authorityEpoch: 7,
    expiresAtMs: 9_500,
  };
  const store = new MemoryBrowserStateStore();
  const host = new BrowserProfileHost({
    driver: driver({
      async act(payload) {
        assert.deepEqual(payload.typedAction, click);
        return { terminalObserved: true, status: "succeeded", outcomeDigest: D1 };
      },
    }),
    authority: authority(),
    store,
    allowVolatileStore: true,
    clock: () => 1_000,
  });
  await host.openProfile(profileInput({ effectGrants: [clickGrant] }));
  await host.observePage({
    profileId: "profile.1", principalId: "principal.1", generation: 1, observationBudget: 128,
  });
  const receipt = await host.navigateOrAct(operation({
    action: "click",
    typedAction: click,
    finalPayloadDigest: clickDigest,
  }));
  assert.equal(receipt.status, "succeeded");
});

test("runtime composition fails closed on unsafe driver or implicit volatile state", () => {
  const unsafeDriver = driver();
  unsafeDriver.capabilities.networkPolicyEnforced = false;
  assert.throws(() => new BrowserProfileHost({
    driver: unsafeDriver,
    authority: authority(),
    store: new MemoryBrowserStateStore(),
    allowVolatileStore: true,
  }), /networkPolicyEnforced/);

  assert.throws(() => new BrowserProfileHost({
    driver: driver(),
    authority: authority(),
    store: new MemoryBrowserStateStore(),
  }), /durable browser state store/);
});

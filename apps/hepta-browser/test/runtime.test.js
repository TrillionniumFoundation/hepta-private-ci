import assert from "node:assert/strict";
import test from "node:test";

import { BrowserProfileHost } from "../src/runtime.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
const D4 = "4".repeat(64);
const D5 = "5".repeat(64);

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
        finalPayloadDigest: D4,
        authorityEpoch: 7,
        expiresAtMs: 9_500,
      },
    ],
    ...overrides,
  };
}

function driver({ terminalOnReconcile = true } = {}) {
  return {
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
      return terminalOnReconcile
        ? { terminalObserved: true, status: "succeeded", outcomeDigest: D1 }
        : { terminalObserved: false };
    },
    async stop() {
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
    action: "navigate",
    destinationOrigin: "https://example.com",
    finalPayloadDigest: D4,
    effectGrantDigest: D5,
    authorityEpoch: 7,
    deadlineMs: 9_000,
    ...overrides,
  };
}

test("opens, observes, reconciles indeterminate action, and closes", async () => {
  const host = new BrowserProfileHost({ driver: driver(), clock: () => 1_000 });
  const session = await host.openProfile(input());
  assert.equal(session.effectGrantCount, 1);
  const page = await host.observePage({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    observationBudget: 2048,
  });
  assert.equal(page.pageGeneration, 1);
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
});

test("rejects stale page, scope escape, unregistered grant and grant semantic drift", async () => {
  const host = new BrowserProfileHost({ driver: driver(), clock: () => 1_000 });
  await host.openProfile(input());
  await host.observePage({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    observationBudget: 128,
  });
  await assert.rejects(host.navigateOrAct(operation({ pageGeneration: 2 })), /stale page generation/);
  await assert.rejects(
    host.navigateOrAct(operation({ destinationOrigin: "https://other.example" })),
    /outside the profile grant/,
  );
  await assert.rejects(
    host.navigateOrAct(operation({ effectGrantDigest: D2 })),
    /not registered/,
  );
  await assert.rejects(
    host.navigateOrAct(operation({ finalPayloadDigest: D3 })),
    /does not bind/,
  );
  await assert.rejects(host.navigateOrAct(operation({ authorityEpoch: 8 })), /does not bind/);
});

test("replay rejects every immutable semantic substitution", async () => {
  const host = new BrowserProfileHost({ driver: driver({ terminalOnReconcile: false }), clock: () => 1_000 });
  await host.openProfile(input());
  await host.observePage({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    observationBudget: 128,
  });
  const first = await host.navigateOrAct(operation());
  assert.equal(first.status, "indeterminate");
  for (const mutation of [
    { deadlineMs: 8_999 },
    { operationId: "operation.1", finalPayloadDigest: D3 },
    { operationId: "operation.1", authorityEpoch: 8 },
  ]) {
    await assert.rejects(host.navigateOrAct(operation(mutation)), /changed semantics|does not bind/);
  }
});

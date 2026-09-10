import assert from "node:assert/strict";
import test from "node:test";

import { BrowserProfileHost } from "../src/runtime.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
const D4 = "4".repeat(64);

function input(overrides = {}) {
  return {
    profileId: "profile.1",
    principalId: "principal.1",
    manifestDigest: D1,
    grantDigest: D2,
    generation: 1,
    expiresAtMs: 10_000,
    allowedOrigins: ["https://example.com"],
    ...overrides,
  };
}

function driver() {
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
    async stop() {
      return { stopped: true };
    },
  };
}

test("opens, observes, preserves indeterminate action, and closes", async () => {
  const host = new BrowserProfileHost({ driver: driver(), clock: () => 1_000 });
  const session = await host.openProfile(input());
  assert.equal(session.networkAuthority, false);
  const page = await host.observePage({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    observationBudget: 2048,
  });
  assert.equal(page.pageGeneration, 1);
  const effect = await host.navigateOrAct({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    operationId: "operation.1",
    pageGeneration: 1,
    action: "navigate",
    destinationOrigin: "https://example.com",
    finalPayloadDigest: D4,
    grantPayloadDigest: D4,
    deadlineMs: 9_000,
  });
  assert.equal(effect.status, "indeterminate");
  assert.equal(effect.terminalObserved, false);
  const closed = await host.closeProfile({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
  });
  assert.equal(closed.terminalObserved, true);
});

test("rejects stale page, scope escape, and payload drift", async () => {
  const host = new BrowserProfileHost({ driver: driver(), clock: () => 1_000 });
  await host.openProfile(input());
  await host.observePage({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    observationBudget: 128,
  });
  const common = {
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    operationId: "operation.2",
    pageGeneration: 1,
    action: "click",
    destinationOrigin: "https://example.com",
    finalPayloadDigest: D3,
    grantPayloadDigest: D3,
    deadlineMs: 9_000,
  };
  await assert.rejects(
    host.navigateOrAct({ ...common, pageGeneration: 2 }),
    /stale page generation/,
  );
  await assert.rejects(
    host.navigateOrAct({ ...common, destinationOrigin: "https://other.example" }),
    /outside the profile grant/,
  );
  await assert.rejects(
    host.navigateOrAct({ ...common, grantPayloadDigest: D4 }),
    /final payload/,
  );
});

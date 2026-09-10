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

function driver({ terminal = false } = {}) {
  const calls = [];
  let pageGeneration = 0;
  return {
    calls,
    async start(value) {
      calls.push(["start", value]);
      return { started: true, processId: "servo.process.1" };
    },
    async observe(value) {
      calls.push(["observe", value]);
      pageGeneration += 1;
      return {
        pageGeneration,
        documentDigest: pageGeneration === 1 ? D3 : D4,
        origin: "https://example.com",
      };
    },
    async act(value) {
      calls.push(["act", value]);
      return terminal
        ? { terminalObserved: true, status: "succeeded", outcomeDigest: D4 }
        : { terminalObserved: false };
    },
    async stop(value) {
      calls.push(["stop", value]);
      return { stopped: true };
    },
  };
}

async function openedHost(options) {
  const io = driver(options);
  const host = new BrowserProfileHost({ driver: io, clock: () => 1_000 });
  await host.openProfile(input());
  await host.observePage({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    observationBudget: 2048,
  });
  return { host, io };
}

function action(overrides = {}) {
  return {
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
    ...overrides,
  };
}

test("opens, observes, preserves indeterminate action, and closes", async () => {
  const { host } = await openedHost();
  const effect = await host.navigateOrAct(action());
  assert.equal(effect.status, "indeterminate");
  assert.equal(effect.terminalObserved, false);
  assert.equal(effect.networkAuthority, false);
  const closed = await host.closeProfile({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
  });
  assert.equal(closed.terminalObserved, true);
});

test("identical retry is observation-only and does not repeat the driver effect", async () => {
  const { host, io } = await openedHost({ terminal: true });
  const first = await host.navigateOrAct(action());
  const second = await host.navigateOrAct(action());
  assert.strictEqual(second, first);
  assert.equal(io.calls.filter(([name]) => name === "act").length, 1);
});

test("replay binds action, destination, page, grant, payload, and deadline", async () => {
  const { host } = await openedHost();
  await host.navigateOrAct(action());
  const mutations = [
    { action: "click" },
    { destinationOrigin: "https://example.com:444" },
    { pageGeneration: 2 },
    { grantPayloadDigest: D3 },
    { finalPayloadDigest: D3, grantPayloadDigest: D3 },
    { deadlineMs: 8_000 },
  ];
  for (const mutation of mutations) {
    await assert.rejects(
      host.navigateOrAct(action(mutation)),
      /changed semantics|outside the profile grant/,
    );
  }
});

test("rejects stale page, scope escape, payload drift, and generation drift", async () => {
  const { host } = await openedHost();
  await assert.rejects(
    host.navigateOrAct(action({ operationId: "operation.2", pageGeneration: 2 })),
    /stale page generation/,
  );
  await assert.rejects(
    host.navigateOrAct(
      action({ operationId: "operation.3", destinationOrigin: "https://other.example" }),
    ),
    /outside the profile grant/,
  );
  await assert.rejects(
    host.navigateOrAct(action({ operationId: "operation.4", grantPayloadDigest: D3 })),
    /final payload/,
  );
  await assert.rejects(
    host.navigateOrAct(action({ operationId: "operation.5", generation: 2 })),
    /generation mismatch/,
  );
});

test("an old identical retry remains observation-only after the page advances", async () => {
  const { host, io } = await openedHost({ terminal: true });
  const first = await host.navigateOrAct(action());
  await host.observePage({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    observationBudget: 2048,
  });
  const replay = await host.navigateOrAct(action());
  assert.strictEqual(replay, first);
  assert.equal(io.calls.filter(([name]) => name === "act").length, 1);
});

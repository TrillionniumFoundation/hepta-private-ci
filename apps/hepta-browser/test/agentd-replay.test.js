import assert from "node:assert/strict";
import test from "node:test";
import { PassThrough } from "node:stream";
import { browserActionDigest } from "../src/action.js";
import { BrowserProfileHost } from "../src/runtime.js";
import { MemoryBrowserOperationJournal } from "../src/journal.js";
import { browserReplayEvidence } from "../src/replay-evidence.js";
import {
  AgentdBrowserChannel,
  BrowserAgentdService,
  ParentFinalUseAuthority,
} from "../src/agentd-service.js";

const D1 = "1".repeat(64);
const W1 = "a".repeat(64);

for (const terminalObserved of [false, true]) {
  test(
    `historical ${terminalObserved ? "terminal" : "indeterminate"} navigate RPC proves a read-only replay before authority`,
    { timeout: 2_000 },
    async (t) => {
      const parentToChild = new PassThrough();
      const childToParent = new PassThrough();
      let running;
      t.after(async () => {
        parentToChild.end();
        childToParent.end();
        await running?.catch(() => {});
        parentToChild.destroy();
        childToParent.destroy();
      });
      const parent = new AgentdBrowserChannel({
        input: childToParent,
        output: parentToChild,
      });
      const child = new AgentdBrowserChannel({
        input: parentToChild,
        output: childToParent,
      });
      const authority = new ParentFinalUseAuthority(child);
      let dispatchCalls = 0;
      let now = 1_000;
      const host = new BrowserProfileHost({
        authority,
        journal: new MemoryBrowserOperationJournal(),
        clock: () => now,
        driver: {
          async start() {
            return { started: true, processId: "servo.process.1" };
          },
          async observe() {
            return {
              pageGeneration: 1,
              documentDigest: D1,
              origin: "https://example.com",
            };
          },
          async dispatch() {
            dispatchCalls += 1;
            return terminalObserved
              ? {
                  terminalObserved: true,
                  status: "succeeded",
                  outcomeDigest: D1,
                }
              : { terminalObserved: false };
          },
          async reconcile() {
            return { terminalObserved: false };
          },
          async stop() {
            return { stopped: true };
          },
        },
      });
      const typedAction = {
        kind: "navigate",
        url: "https://example.com/path",
        policyDigest: D1,
        expectedRevision: 7,
      };
      const finalPayloadDigest = browserActionDigest(typedAction);
      const owner = {
        profileId: "profile.1",
        principalId: "principal.1",
        generation: 1,
      };
      await host.openProfile({
        ...owner,
        manifestDigest: D1,
        grantDigest: D1,
        expiresAtMs: 10_000,
        allowedOrigins: ["https://example.com"],
        effectGrants: [
          {
            grantDigest: D1,
            action: "navigate",
            destinationOrigin: "https://example.com",
            finalPayloadDigest,
            authorityEpoch: 7,
            expiresAtMs: 10_000,
          },
        ],
      });
      await host.observePage({ ...owner, observationBudget: 128 });
      const input = {
        ...owner,
        operationId: "operation.1",
        pageGeneration: 1,
        typedAction,
        destinationOrigin: "https://example.com",
        finalPayloadDigest,
        effectGrantDigest: D1,
        authorityEpoch: 7,
        deadlineMs: 9_000,
      };
      const service = new BrowserAgentdService({
        host,
        channel: child,
        authority,
      });
      running = service.run();
      await parent.send("request", "request.first", {
        method: "navigate_or_act",
        input,
      });
      const challenge = await parent.nextFrame();
      assert.equal(challenge.kind, "authority_challenge");
      await parent.send("authority_enter", "request.first", {
        authorized: true,
        witnessDigest: W1,
        requestDigest: challenge.payload.requestDigest,
        authorityEpoch: 7,
      });
      assert.equal((await parent.nextFrame()).kind, "dispatch_boundary");
      const first = await parent.nextFrame();
      assert.equal(first.kind, "response");
      assert.deepEqual(Object.keys(first.payload).sort(), ["ok", "result"]);
      assert.equal(first.payload.result.terminalObserved, terminalObserved);

      // The dispatched page snapshot is consumed and both authority deadlines
      // are past. Exact history remains observable without another fence.
      now = 20_000;
      await parent.send("request", "request.replay", {
        method: "navigate_or_act",
        input,
      });
      const replay = await parent.nextFrame();
      assert.equal(replay.kind, "response");
      assert.deepEqual(Object.keys(replay.payload).sort(), [
        "ok",
        "replay",
        "result",
      ]);
      assert.deepEqual(replay.payload.result, first.payload.result);
      assert.deepEqual(replay.payload.replay, {
        schema: "hepta.browser.replay-observation.v1",
        ...owner,
        operationId: input.operationId,
        requestDigest: challenge.payload.requestDigest,
        semanticDigest: first.payload.result.semanticDigest,
      });
      assert.equal(dispatchCalls, 1);
      for (const flag of [
        "networkAuthority",
        "filesystemAuthority",
        "credentialExportAuthority",
      ]) {
        assert.equal(replay.payload.result[flag], false);
      }

      await parent.send("request", "request.changed", {
        method: "navigate_or_act",
        input: { ...input, deadlineMs: 8_000 },
      });
      const changed = await parent.nextFrame();
      assert.equal(changed.kind, "response");
      assert.equal(changed.payload.ok, false);
      assert.match(changed.payload.error, /changed semantics/);
      assert.equal(changed.payload.replay, undefined);
      assert.equal(dispatchCalls, 1);
      parentToChild.end();
      await running;
    },
  );
}

test("a historical receipt clone cannot retroactively mark the first dispatch result", async () => {
  const authority = {
    async withVerifiedUse(request, consumer) {
      return consumer({
        authorized: true,
        requestDigest: request.requestDigest,
        authorityEpoch: request.authorityEpoch,
        witnessDigest: W1,
      });
    },
  };
  const host = new BrowserProfileHost({
    authority,
    journal: new MemoryBrowserOperationJournal(),
    clock: () => 1_000,
    driver: {
      async start() {
        return { started: true, processId: "servo.process.1" };
      },
      async observe() {},
      async dispatch() {
        return { terminalObserved: false };
      },
      async reconcile() {},
      async stop() {},
    },
  });
  const typedAction = {
    kind: "navigate",
    url: "https://example.com/path",
    policyDigest: D1,
    expectedRevision: 7,
  };
  const finalPayloadDigest = browserActionDigest(typedAction);
  const owner = {
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
  };
  await host.openProfile({
    ...owner,
    manifestDigest: D1,
    grantDigest: D1,
    expiresAtMs: 10_000,
    allowedOrigins: ["https://example.com"],
    effectGrants: [
      {
        grantDigest: D1,
        action: "navigate",
        destinationOrigin: "https://example.com",
        finalPayloadDigest,
        authorityEpoch: 7,
        expiresAtMs: 10_000,
      },
    ],
  });
  const input = {
    ...owner,
    operationId: "operation.1",
    pageGeneration: 0,
    typedAction,
    destinationOrigin: "https://example.com",
    finalPayloadDigest,
    effectGrantDigest: D1,
    authorityEpoch: 7,
    deadlineMs: 9_000,
  };
  const first = await host.navigateOrAct(input);
  const replay = await host.navigateOrAct(input);
  assert.notEqual(first, replay);
  assert.deepEqual(first, replay);
  assert.equal(browserReplayEvidence(first), undefined);
  assert.equal(browserReplayEvidence({ ...replay }), undefined);
  assert.equal(Object.isFrozen(replay), true);
  assert.equal(Object.isFrozen(browserReplayEvidence(replay)), true);
});

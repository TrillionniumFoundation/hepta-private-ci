import assert from "node:assert/strict";
import test from "node:test";

import { browserActionDigest } from "../src/action.js";
import { MemoryBrowserOperationJournal } from "../src/journal.js";
import { BrowserProfileHost } from "../src/runtime.js";

const A = "https://example.com";
const B = "https://other.example";
const DIGEST = "1".repeat(64);
const GRANT = "2".repeat(64);
const WITNESS = "3".repeat(64);
const IDENTITY = {
  profileId: "profile.1",
  principalId: "principal.1",
  generation: 1,
};

async function fixture(
  typedAction,
  { observedOrigin = A, destinationOrigin = B, allowedOrigins = [A, B] } = {},
) {
  const state = {
    observedOrigin,
    pageGeneration: 0,
    authorizations: 0,
    dispatches: 0,
    observeOverride: null,
  };
  const journal = new MemoryBrowserOperationJournal();
  const host = new BrowserProfileHost({
    clock: () => 1000,
    driverCallTimeoutMs: 20,
    journal,
    authority: {
      async withVerifiedUse(request, consume) {
        state.authorizations += 1;
        return consume({
          authorized: true,
          witnessDigest: WITNESS,
          requestDigest: request.requestDigest,
          authorityEpoch: 1,
        });
      },
    },
    driver: {
      async start() {
        return { started: true, processId: "servo.process.1" };
      },
      async observe() {
        state.pageGeneration += 1;
        if (state.observeOverride) return state.observeOverride();
        return {
          pageGeneration: state.pageGeneration,
          documentDigest: DIGEST,
          origin: state.observedOrigin,
        };
      },
      async dispatch() {
        state.dispatches += 1;
        return {
          terminalObserved: true,
          status: "succeeded",
          outcomeDigest: DIGEST,
        };
      },
      async reconcile() {
        throw new Error("terminal replay must not reconcile");
      },
      async stop() {
        return { stopped: true };
      },
    },
  });
  const finalPayloadDigest = browserActionDigest(typedAction);
  await host.openProfile({
    ...IDENTITY,
    manifestDigest: DIGEST,
    grantDigest: GRANT,
    expiresAtMs: 10000,
    allowedOrigins,
    effectGrants: [
      {
        grantDigest: GRANT,
        action: typedAction.kind,
        destinationOrigin,
        finalPayloadDigest,
        authorityEpoch: 1,
        expiresAtMs: 9000,
      },
    ],
  });
  const observe = () =>
    host.observePage({ ...IDENTITY, observationBudget: 128 });
  await observe();
  const operation = {
    ...IDENTITY,
    operationId: "operation.1",
    pageGeneration: 1,
    typedAction,
    destinationOrigin,
    finalPayloadDigest,
    effectGrantDigest: GRANT,
    authorityEpoch: 1,
    deadlineMs: 8000,
  };
  return { state, host, journal, observe, operation };
}

const DOCUMENT_ACTIONS = [
  { kind: "click", selector: "#confirm" },
  { kind: "type", selector: "#name", text: "hello" },
  { kind: "focus", selector: "#name" },
  { kind: "scroll", deltaX: 0, deltaY: 100 },
  { kind: "wait", condition: "load-complete", timeoutMs: 100 },
  { kind: "credential", selector: "#password", credentialRef: "credential.1" },
  {
    kind: "upload",
    selector: "#file",
    fileRef: "file.1",
    fileDigest: DIGEST,
    maxBytes: 1024,
  },
];

for (const typedAction of DOCUMENT_ACTIONS) {
  test(`${typedAction.kind} rejects another allowed origin before authority or intent`, async () => {
    const { state, host, journal, observe, operation } =
      await fixture(typedAction);
    await assert.rejects(
      host.navigateOrAct(operation),
      /observed document origin/,
    );
    assert.deepEqual(
      {
        authorizations: state.authorizations,
        dispatches: state.dispatches,
        journal: await journal.listOperations(IDENTITY.profileId, 1),
      },
      { authorizations: 0, dispatches: 0, journal: [] },
    );

    // A redirect needs a new observation; historical recovery remains bound
    // to the original action rather than the page currently displayed.
    state.observedOrigin = B;
    await observe();
    const admitted = { ...operation, pageGeneration: 2 };
    const receipt = await host.navigateOrAct(admitted);
    state.observedOrigin = A;
    await observe();
    assert.deepEqual(await host.navigateOrAct(admitted), receipt);
    assert.deepEqual(await host.reconcilePersistedOperation(admitted), receipt);
    assert.deepEqual(
      { authorizations: state.authorizations, dispatches: state.dispatches },
      { authorizations: 1, dispatches: 1 },
    );
  });
}

for (const [observedOrigin, destinationOrigin] of [
  ["https://EXAMPLE.com:443/", A],
  ["https://例え.テスト/", "https://xn--r8jz45g.xn--zckzah:443/"],
  ["http://example.com:80/", "http://EXAMPLE.COM/"],
]) {
  test(`document origins normalize before matching ${observedOrigin}`, async () => {
    const { host, operation } = await fixture(DOCUMENT_ACTIONS[0], {
      observedOrigin,
      destinationOrigin,
      allowedOrigins: [destinationOrigin],
    });
    assert.equal((await host.navigateOrAct(operation)).status, "succeeded");
  });
}

for (const typedAction of [
  {
    kind: "navigate",
    url: `${B}/new`,
    policyDigest: DIGEST,
    expectedRevision: 1,
  },
  { kind: "download", url: `${B}/file`, maxBytes: 1024 },
]) {
  test(`${typedAction.kind} binds its explicit URL rather than the source document origin`, async () => {
    const { host, operation } = await fixture(typedAction);
    assert.equal((await host.navigateOrAct(operation)).status, "succeeded");
  });
}

for (const [failure, observeOverride, error] of [
  [
    "throw",
    () => {
      throw new Error("observation lost after worker snapshot advanced");
    },
    /observation lost/,
  ],
  ["timeout", () => new Promise(() => {}), /timed out/],
  [
    "invalid digest",
    () => ({ pageGeneration: 2, documentDigest: "invalid", origin: A }),
    /documentDigest/,
  ],
  [
    "stale generation",
    () => ({ pageGeneration: 1, documentDigest: DIGEST, origin: A }),
    /generation did not advance/,
  ],
]) {
  test(`observation refresh ${failure} cannot reuse the previous actionable snapshot`, async () => {
    const { host, state, journal, observe, operation } = await fixture(
      DOCUMENT_ACTIONS[0],
      { destinationOrigin: A },
    );
    state.observeOverride = observeOverride;
    await assert.rejects(observe(), error);
    await assert.rejects(
      host.navigateOrAct(operation),
      /stale page generation/,
    );
    assert.deepEqual(
      {
        authorizations: state.authorizations,
        dispatches: state.dispatches,
        journal: await journal.listOperations(IDENTITY.profileId, 1),
      },
      { authorizations: 0, dispatches: 0, journal: [] },
    );
    state.observeOverride = null;
    const page = await observe();
    assert.equal(
      (
        await host.navigateOrAct({
          ...operation,
          pageGeneration: page.pageGeneration,
        })
      ).status,
      "succeeded",
    );
  });
}

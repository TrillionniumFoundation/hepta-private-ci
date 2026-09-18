import assert from "node:assert/strict";
import test from "node:test";

import { ControlPlaneApp } from "../src/browser-app.js";
import { loadBrowserBootstrap } from "../src/browser-host.js";
import { SameOriginHttpTransport } from "../src/http-transport.js";
import { LocalStoragePendingStore } from "../src/pending-store.js";
import { ERROR_CODES } from "../src/protocol.js";
import { RuntimeClient } from "../src/runtime-client.js";
import { acquireControlPlaneLease, startControlPlane } from "../src/web-main.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);

class MemoryStorage {
  values = new Map();
  getItem(key) { return this.values.has(key) ? this.values.get(key) : null; }
  setItem(key, value) { this.values.set(key, String(value)); }
}

function frozenTimer() {
  return { unref() {} };
}

function displayedViewBinding({
  sessionId = "session.1",
  connectionGeneration = 1,
  generation = 7,
  revision = 9,
  digest = D2,
} = {}) {
  return Object.freeze({ sessionId, connectionGeneration, generation, revision, digest });
}

async function connectWithSnapshot(client, sessionId = "session.1", generation = 1) {
  await client.connect({ endpointId: "runtime.1", protocolVersion: 1, manifestDigest: D1 });
  client.applySnapshot({
    sessionId,
    connectionGeneration: generation,
    generation: 7,
    revision: 9,
    digest: D2,
    modules: [{ moduleId: "runtime.agentd", status: "ready", revision: 4, digest: D3 }],
  });
}

test("close drains in-flight acknowledgement under immutable origin provenance before reconnect", async () => {
  let connection = 0;
  let requestResolve;
  let requestStartedResolve;
  const requestStarted = new Promise((resolve) => { requestStartedResolve = resolve; });
  const transport = {
    async connect(input) {
      connection += 1;
      return { authenticated: true, sessionId: `session.${connection}`, connectionGeneration: connection, protocolVersion: input.protocolVersion };
    },
    async request(method, input) {
      requestStartedResolve({ method, input });
      return new Promise((resolve) => { requestResolve = resolve; });
    },
    async reconcile() { return null; },
    async close() {},
  };
  const client = new RuntimeClient({ transport, setTimer: frozenTimer, clearTimer: () => {} });
  await connectWithSnapshot(client);
  const submission = client.submitRequest({
    operationId: "operation.race",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: 4,
    displayedView: displayedViewBinding(),
  });
  const started = await requestStarted;
  let closeSettled = false;
  const firstClose = client.close().then(() => { closeSettled = true; });
  const secondClose = client.close();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(closeSettled, false);
  await assert.rejects(
    client.connect({ endpointId: "runtime.1", protocolVersion: 1, manifestDigest: D1 }),
    (error) => error.code === ERROR_CODES.NOT_CONNECTED,
  );

  requestResolve({
    accepted: true,
    method: started.method,
    sessionId: started.input.sessionId,
    connectionGeneration: started.input.connectionGeneration,
    runtimeGeneration: started.input.runtimeGeneration,
    operationId: started.input.operationId,
    semanticDigest: started.input.semanticDigest,
  });
  const ack = await submission;
  await Promise.all([firstClose, secondClose]);
  assert.equal(ack.accepted, true);
  assert.equal(ack.originSessionId, "session.1");

  const session = await client.connect({
    endpointId: "runtime.1",
    protocolVersion: 1,
    manifestDigest: D1,
  });
  assert.equal(session.sessionId, "session.2");
  assert.equal(session.pendingReconciliation, 1);
});

test("offline-style reconciliation pause cancels automatic retry without discarding pending identity", async () => {
  let scheduled = null;
  let cleared = 0;
  const transport = {
    async connect(input) {
      return {
        authenticated: true,
        sessionId: "session.1",
        connectionGeneration: 1,
        protocolVersion: input.protocolVersion,
      };
    },
    async request() {
      throw new Error("ack lost");
    },
    async reconcile() {
      assert.fail("paused automatic reconciliation must not run");
    },
    async close() {},
  };
  const client = new RuntimeClient({
    transport,
    setTimer(callback, delay) {
      scheduled = { callback, delay };
      return scheduled;
    },
    clearTimer(timer) {
      if (timer === scheduled) cleared += 1;
      scheduled = null;
    },
  });
  await connectWithSnapshot(client);
  const acknowledgement = await client.submitRequest({
    operationId: "operation.pause-reconcile",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: 4,
    displayedView: displayedViewBinding(),
  });
  assert.equal(acknowledgement.status, "indeterminate");
  assert.ok(scheduled);
  assert.equal(client.readView().pending, 1);

  client.pauseReconciliation();
  assert.equal(cleared, 1);
  assert.equal(scheduled, null);
  assert.equal(client.readView().pending, 1);
});

test("paused reconciliation survives a late acknowledgement and only a fresh connect resumes it", async () => {
  let connection = 0;
  let requestResolve;
  let requestStartedResolve;
  const requestStarted = new Promise((resolve) => { requestStartedResolve = resolve; });
  let timerCalls = 0;
  let reconcileCalls = 0;
  const transport = {
    async connect(input) {
      connection += 1;
      return {
        authenticated: true,
        sessionId: `session.${connection}`,
        connectionGeneration: connection,
        protocolVersion: input.protocolVersion,
      };
    },
    async request(method, input) {
      requestStartedResolve({ method, input });
      return new Promise((resolve) => { requestResolve = resolve; });
    },
    async reconcile() {
      reconcileCalls += 1;
      return null;
    },
    async close() {},
  };
  const client = new RuntimeClient({
    transport,
    setTimer() {
      timerCalls += 1;
      return { unref() {} };
    },
    clearTimer: () => {},
  });
  await connectWithSnapshot(client);

  const submission = client.submitRequest({
    operationId: "operation.pause-late-ack",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: 4,
    displayedView: displayedViewBinding(),
  });
  const started = await requestStarted;
  client.pauseReconciliation();
  requestResolve({
    accepted: true,
    method: started.method,
    sessionId: started.input.sessionId,
    connectionGeneration: started.input.connectionGeneration,
    runtimeGeneration: started.input.runtimeGeneration,
    operationId: started.input.operationId,
    semanticDigest: started.input.semanticDigest,
  });
  const acknowledgement = await submission;
  assert.equal(acknowledgement.accepted, true);
  assert.equal(timerCalls, 0);
  assert.equal(reconcileCalls, 0);

  const session = await client.connect({
    endpointId: "runtime.1",
    protocolVersion: 1,
    manifestDigest: D1,
  });
  assert.equal(session.sessionId, "session.2");
  assert.equal(reconcileCalls, 1);
  assert.equal(timerCalls, 1);
});

test("closing client cannot re-arm or manually start reconciliation from a late acknowledgement", async () => {
  let requestResolve;
  let requestStartedResolve;
  let closeResolve;
  const requestStarted = new Promise((resolve) => { requestStartedResolve = resolve; });
  const closeStarted = new Promise((resolve) => { closeResolve = resolve; });
  let finishClose;
  const closeGate = new Promise((resolve) => { finishClose = resolve; });
  let timerCalls = 0;
  let reconcileCalls = 0;
  const transport = {
    async connect(input) {
      return {
        authenticated: true,
        sessionId: "session.1",
        connectionGeneration: 1,
        protocolVersion: input.protocolVersion,
      };
    },
    async request(method, input) {
      requestStartedResolve({ method, input });
      return new Promise((resolve) => { requestResolve = resolve; });
    },
    async reconcile() {
      reconcileCalls += 1;
      return null;
    },
    async close() {
      closeResolve();
      await closeGate;
    },
  };
  const client = new RuntimeClient({
    transport,
    setTimer: () => {
      timerCalls += 1;
      return { unref() {} };
    },
    clearTimer: () => {},
  });
  await connectWithSnapshot(client);

  const submission = client.submitRequest({
    operationId: "operation.close-late-ack",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: 4,
    displayedView: displayedViewBinding(),
  });
  const started = await requestStarted;
  const closing = client.close();
  await closeStarted;

  requestResolve({
    accepted: true,
    method: started.method,
    sessionId: started.input.sessionId,
    connectionGeneration: started.input.connectionGeneration,
    runtimeGeneration: started.input.runtimeGeneration,
    operationId: started.input.operationId,
    semanticDigest: started.input.semanticDigest,
  });
  const acknowledgement = await submission;
  assert.equal(acknowledgement.accepted, true);
  assert.equal(timerCalls, 0);
  assert.equal(reconcileCalls, 0);
  await assert.rejects(
    client.reconcilePending({ force: true }),
    (error) => error.code === ERROR_CODES.NOT_CONNECTED,
  );

  finishClose();
  await closing;
  assert.equal(timerCalls, 0);
  assert.equal(reconcileCalls, 0);
});

test("reconnect does not reconcile an operation while its original mutation dispatch is in flight", async () => {
  let connection = 0;
  let reconcileCalls = 0;
  let requestResolve;
  let requestStartedResolve;
  const requestStarted = new Promise((resolve) => { requestStartedResolve = resolve; });
  const transport = {
    async connect(input) {
      connection += 1;
      return {
        authenticated: true,
        sessionId: `session.${connection}`,
        connectionGeneration: connection,
        protocolVersion: input.protocolVersion,
      };
    },
    async request(method, input) {
      requestStartedResolve({ method, input });
      return new Promise((resolve) => { requestResolve = resolve; });
    },
    async reconcile(query) {
      reconcileCalls += 1;
      return {
        ...query,
        status: "succeeded",
        terminalObserved: true,
        outcomeDigest: D3,
      };
    },
    async close() {},
  };
  const client = new RuntimeClient({
    transport,
    setTimer: frozenTimer,
    clearTimer: () => {},
  });
  await connectWithSnapshot(client);

  const submission = client.submitRequest({
    operationId: "operation.reconnect-inflight",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: 4,
    displayedView: displayedViewBinding(),
  });
  const started = await requestStarted;

  const reconnected = await client.connect({
    endpointId: "runtime.1",
    protocolVersion: 1,
    manifestDigest: D1,
  });
  assert.equal(reconnected.sessionId, "session.2");
  assert.equal(reconnected.pendingReconciliation, 1);
  assert.equal(reconcileCalls, 0);
  assert.throws(
    () =>
      client.reconcile({
        operationId: started.input.operationId,
        semanticDigest: started.input.semanticDigest,
        method: started.method,
        sessionId: "session.2",
        connectionGeneration: 2,
        originSessionId: started.input.sessionId,
        originConnectionGeneration: started.input.connectionGeneration,
        runtimeGeneration: started.input.runtimeGeneration,
        status: "succeeded",
        terminalObserved: true,
        outcomeDigest: D3,
      }),
    (error) => error.code === ERROR_CODES.RECONCILIATION_MISMATCH,
  );

  requestResolve({
    accepted: true,
    method: started.method,
    sessionId: started.input.sessionId,
    connectionGeneration: started.input.connectionGeneration,
    runtimeGeneration: started.input.runtimeGeneration,
    operationId: started.input.operationId,
    semanticDigest: started.input.semanticDigest,
  });
  const acknowledgement = await submission;
  assert.equal(acknowledgement.accepted, true);
  assert.equal(reconcileCalls, 0);

  await client.reconcilePending({ force: true });
  assert.equal(reconcileCalls, 1);
  assert.equal(client.readView().pending, 0);
});

test("durable pending identity survives reload without persisting request payload", async () => {
  const storage = new MemoryStorage();
  const store = new LocalStoragePendingStore({ storage, key: "hepta.pending.test" });
  const firstTransport = {
    async connect(input) { return { authenticated: true, sessionId: "session.1", connectionGeneration: 1, protocolVersion: input.protocolVersion }; },
    async request() { throw new Error("ack lost"); },
    async reconcile() { return null; },
    async close() {},
  };
  const first = new RuntimeClient({ transport: firstTransport, pendingStore: store, setTimer: frozenTimer, clearTimer: () => {} });
  await connectWithSnapshot(first);
  const ack = await first.submitRequest({
    operationId: "operation.persist",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: 4,
    displayedView: displayedViewBinding(),
  });
  assert.equal(ack.status, "indeterminate");
  const raw = storage.getItem("hepta.pending.test");
  assert.match(raw, /operation\.persist/);
  assert.equal(raw.includes("runtime.agentd"), false);
  assert.equal(raw.includes("request_retry"), false);

  const secondTransport = {
    async connect(input) { return { authenticated: true, sessionId: "session.2", connectionGeneration: 2, protocolVersion: input.protocolVersion }; },
    async request() { assert.fail("reload reconciliation must not resubmit mutation"); },
    async reconcile(query) {
      return {
        ...query,
        sessionId: "session.2",
        connectionGeneration: 2,
        status: "succeeded",
        terminalObserved: true,
        outcomeDigest: D3,
      };
    },
    async close() {},
  };
  const second = new RuntimeClient({ transport: secondTransport, pendingStore: store, setTimer: frozenTimer, clearTimer: () => {} });
  const session = await second.connect({ endpointId: "runtime.1", protocolVersion: 1, manifestDigest: D1 });
  assert.equal(session.pendingReconciliation, 0);
  assert.equal(second.readView().pending, 0);
  assert.match(storage.getItem("hepta.pending.test"), /"entries":\[\]/);
});

test("persistence failure before dispatch fails closed and never crosses transport", async () => {
  let requests = 0;
  const store = { load: () => [], save: () => { throw new Error("quota"); } };
  const transport = {
    async connect(input) { return { authenticated: true, sessionId: "session.1", connectionGeneration: 1, protocolVersion: input.protocolVersion }; },
    async request() { requests += 1; return {}; },
    async reconcile() { return null; },
    async close() {},
  };
  const client = new RuntimeClient({ transport, pendingStore: store, setTimer: frozenTimer, clearTimer: () => {} });
  await connectWithSnapshot(client);
  await assert.rejects(
    client.submitRequest({ operationId: "operation.no-store", subjectId: "runtime.agentd", action: "request_retry", expectedRevision: 4, displayedView: displayedViewBinding() }),
    (error) => error.code === ERROR_CODES.PERSISTENCE_UNAVAILABLE,
  );
  assert.equal(requests, 0);
});

class FakeElement {
  constructor(tagName, ownerDocument) {
    this.tagName = tagName;
    this.ownerDocument = ownerDocument;
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.textContent = "";
    this.disabled = false;
  }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = [...children]; }
  addEventListener(name, listener) { this.listeners.set(name, listener); }
  focus() { this.ownerDocument.activeElement = this; }
}
class FakeDocument {
  activeElement = null;
  createElement(tagName) { return new FakeElement(tagName, this); }
}
function allElements(root) {
  const result = [];
  const visit = (element) => { result.push(element); for (const child of element.children) visit(child); };
  visit(root);
  return result;
}
function sampleView() {
  return Object.freeze({
    stale: false,
    sessionId: "session.1",
    connectionGeneration: 1,
    generation: 7,
    revision: 9,
    digest: D2,
    pending: 0,
    indeterminate: 0,
    recoveryRequired: 0,
    modules: Object.freeze([
      Object.freeze({
        moduleId: "runtime.agentd",
        status: "ready",
        revision: 4,
        digest: D3,
        ready: true,
      }),
    ]),
  });
}

test("browser action lock collapses rapid duplicate clicks and restores focus after rerender", async () => {
  const document = new FakeDocument();
  const root = new FakeElement("div", document);
  let idCalls = 0;
  let submitCalls = 0;
  let releaseConfirm;
  const confirmation = new Promise((resolve) => { releaseConfirm = resolve; });
  const client = {
    readView: () => sampleView(),
    async submitRequest(request) { submitCalls += 1; return { operationId: request.operationId, status: "pending" }; },
    async requestStop() { assert.fail("stop should not run"); },
  };
  const app = new ControlPlaneApp({
    root,
    client,
    operationIdFactory: () => `operation.${++idCalls}`,
    confirmAction: () => confirmation,
  });
  app.render();
  const retry = allElements(root).find((e) => e.tagName === "button" && e.textContent.startsWith("Retry "));
  retry.focus();
  retry.listeners.get("click")();
  retry.listeners.get("click")();
  assert.equal(idCalls, 1);
  releaseConfirm(true);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(submitCalls, 1);
  assert.equal(document.activeElement?.textContent, "Retry runtime.agentd");
});

test("browser logical action lock survives a polling rerender while acknowledgement is in flight", async () => {
  const document = new FakeDocument();
  const root = new FakeElement("div", document);
  let currentView = sampleView();
  let idCalls = 0;
  let submitCalls = 0;
  let requestResolve;
  let requestStartedResolve;
  const requestStarted = new Promise((resolve) => { requestStartedResolve = resolve; });
  const client = {
    readView: () => currentView,
    async submitRequest(request) {
      submitCalls += 1;
      requestStartedResolve(request);
      return new Promise((resolve) => { requestResolve = () => resolve({ operationId: request.operationId, status: "pending" }); });
    },
    async requestStop() { assert.fail("stop should not run"); },
  };
  const app = new ControlPlaneApp({
    root,
    client,
    operationIdFactory: () => `operation.${++idCalls}`,
    confirmAction: async () => true,
  });

  app.render();
  const firstRetry = allElements(root).find(
    (element) => element.tagName === "button" && element.textContent.startsWith("Retry "),
  );
  firstRetry.listeners.get("click")();
  await requestStarted;
  assert.equal(submitCalls, 1);

  currentView = Object.freeze({
    ...sampleView(),
    generation: 8,
    revision: 10,
    modules: Object.freeze([
      Object.freeze({
        moduleId: "runtime.agentd",
        status: "ready",
        revision: 5,
        digest: D3,
        ready: true,
      }),
    ]),
  });
  app.render();
  const rerenderedRetry = allElements(root).find(
    (element) => element.tagName === "button" && element.textContent.startsWith("Retry "),
  );
  assert.equal(rerenderedRetry.disabled, true);

  // Fake DOM dispatch does not suppress disabled listeners, so invoking it
  // directly also verifies the handler-level logical lock.
  rerenderedRetry.listeners.get("click")();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(idCalls, 1);
  assert.equal(submitCalls, 1);

  requestResolve();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(submitCalls, 1);
});

test("browser host can block mutations after snapshot connectivity loss", async () => {
  const document = new FakeDocument();
  const root = new FakeElement("div", document);
  let submissions = 0;
  const client = {
    readView: () => sampleView(),
    async submitRequest() { submissions += 1; return { operationId: "x", status: "pending" }; },
    async requestStop() { submissions += 1; return { operationId: "x", status: "pending" }; },
  };
  const app = new ControlPlaneApp({ root, client, confirmAction: async () => true });
  app.render();
  app.setMutationBlock("Runtime snapshot refresh failed.");
  const buttons = allElements(root).filter((e) => e.tagName === "button");
  assert.equal(buttons.every((button) => button.disabled), true);
  buttons[1].listeners.get("click")();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(submissions, 0);
});

test("same-origin transport enforces CSRF, credential mode and origin policy", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    if (url.endsWith("/csrf")) {
      return new Response(JSON.stringify({ token: "csrf-token" }), { status: 200, headers: { "content-type": "application/json" } });
    }
    return new Response(JSON.stringify({ authenticated: true }), { status: 200, headers: { "content-type": "application/json" } });
  };
  const transport = new SameOriginHttpTransport({ baseUrl: "/api/ui-control", origin: "https://control.example", fetchImpl });
  await transport.connect({ endpointId: "runtime.1" });
  assert.equal(calls.length, 2);
  assert.equal(calls[1].options.credentials, "same-origin");
  assert.equal(calls[1].options.redirect, "error");
  assert.equal(calls[1].options.headers.get("x-hepta-csrf"), "csrf-token");
  assert.throws(
    () => new SameOriginHttpTransport({ baseUrl: "https://evil.example/api", origin: "https://control.example", fetchImpl }),
    (error) => error.code === ERROR_CODES.TRANSPORT_SECURITY_VIOLATION,
  );
});

test("pending store rejects tampered schema instead of silently discarding it", () => {
  const storage = new MemoryStorage();
  storage.setItem("x", JSON.stringify({ schema: "evil.v1", entries: [] }));
  const store = new LocalStoragePendingStore({ storage, key: "x" });
  assert.throws(() => store.load(), (error) => error.code === ERROR_CODES.PERSISTENCE_UNAVAILABLE);
});

test("snapshot and module accessor ingress fails without invoking getters", async () => {
  const transport = {
    async connect(input) {
      return {
        authenticated: true,
        sessionId: "session.1",
        connectionGeneration: 1,
        protocolVersion: input.protocolVersion,
      };
    },
    async request() { assert.fail("mutation should not run"); },
    async reconcile() { return null; },
    async close() {},
  };
  const client = new RuntimeClient({
    transport,
    setTimer: frozenTimer,
    clearTimer: () => {},
  });
  await client.connect({ endpointId: "runtime.1", protocolVersion: 1, manifestDigest: D1 });

  let snapshotGetterCalls = 0;
  const hostileSnapshot = {
    sessionId: "session.1",
    connectionGeneration: 1,
    revision: 1,
    digest: D2,
    modules: [],
  };
  Object.defineProperty(hostileSnapshot, "generation", {
    enumerable: true,
    get() {
      snapshotGetterCalls += 1;
      return 1;
    },
  });
  assert.throws(
    () => client.applySnapshot(hostileSnapshot),
    (error) => error.code === ERROR_CODES.INVALID_INPUT,
  );
  assert.equal(snapshotGetterCalls, 0);

  let moduleGetterCalls = 0;
  const hostileModule = {
    moduleId: "runtime.agentd",
    revision: 1,
    digest: D3,
  };
  Object.defineProperty(hostileModule, "status", {
    enumerable: true,
    get() {
      moduleGetterCalls += 1;
      return "ready";
    },
  });
  assert.throws(
    () =>
      client.applySnapshot({
        sessionId: "session.1",
        connectionGeneration: 1,
        generation: 1,
        revision: 1,
        digest: D2,
        modules: [hostileModule],
      }),
    (error) => error.code === ERROR_CODES.INVALID_INPUT,
  );
  assert.equal(moduleGetterCalls, 0);
});

test("confirmation is invalidated when host blocks mutation before submit", async () => {
  const document = new FakeDocument();
  const root = new FakeElement("div", document);
  let submissions = 0;
  let releaseConfirm;
  const confirmation = new Promise((resolve) => { releaseConfirm = resolve; });
  const client = {
    readView: () => sampleView(),
    async submitRequest() {
      submissions += 1;
      return { operationId: "operation.blocked", status: "pending" };
    },
    async requestStop() { assert.fail("stop should not run"); },
  };
  const app = new ControlPlaneApp({
    root,
    client,
    operationIdFactory: () => "operation.blocked",
    confirmAction: () => confirmation,
  });
  app.render();
  const retry = allElements(root).find((e) => e.tagName === "button" && e.textContent.startsWith("Retry "));
  retry.listeners.get("click")();
  app.setMutationBlock("Network connectivity is unavailable.");
  releaseConfirm(true);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(submissions, 0);
  assert.match(
    allElements(root).find((e) => e.attributes.get("role") === "alert")?.textContent ?? "",
    /invalidated/,
  );
});

test("cancelled confirmation restores focus after dialog focus displacement", async () => {
  const document = new FakeDocument();
  const root = new FakeElement("div", document);
  const client = {
    readView: () => sampleView(),
    async submitRequest() { assert.fail("cancelled request must not submit"); },
    async requestStop() { assert.fail("stop should not run"); },
  };
  const app = new ControlPlaneApp({
    root,
    client,
    operationIdFactory: () => "operation.cancelled",
    confirmAction: async () => {
      document.activeElement = new FakeElement("dialog", document);
      return false;
    },
  });
  app.render();
  const retry = allElements(root).find((e) => e.tagName === "button" && e.textContent.startsWith("Retry "));
  retry.focus();
  retry.listeners.get("click")();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(document.activeElement?.textContent, "Retry runtime.agentd");
});

test("chunked transport responses are bounded while streaming", async () => {
  const chunk = new Uint8Array(600_000).fill(120);
  const transport = new SameOriginHttpTransport({
    origin: "https://control.example",
    fetchImpl: async () =>
      new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(chunk);
            controller.enqueue(chunk);
            controller.close();
          },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
  });
  await assert.rejects(
    transport.readSnapshot(),
    (error) => error.code === ERROR_CODES.PROTOCOL_VIOLATION,
  );
});

test("bootstrap streaming bound and JSON media type fail closed", async () => {
  const bootstrapChunk = new Uint8Array(10_000).fill(120);
  await assert.rejects(
    loadBrowserBootstrap({
      origin: "https://control.example",
      fetchImpl: async () =>
        new Response(
          new ReadableStream({
            start(controller) {
              controller.enqueue(bootstrapChunk);
              controller.enqueue(bootstrapChunk);
              controller.close();
            },
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
    }),
    (error) => error.code === ERROR_CODES.PROTOCOL_VIOLATION,
  );

  await assert.rejects(
    loadBrowserBootstrap({
      origin: "https://control.example",
      fetchImpl: async () =>
        new Response("{}", {
          status: 200,
          headers: { "content-type": "application/jsonp" },
        }),
    }),
    (error) => error.code === ERROR_CODES.PROTOCOL_VIOLATION,
  );
});

test("transport POST body rejects accessor-shaped input before CSRF or network I/O", async () => {
  let getterCalls = 0;
  let fetchCalls = 0;
  let csrfCalls = 0;
  const transport = new SameOriginHttpTransport({
    origin: "https://control.example",
    csrfTokenProvider: async () => {
      csrfCalls += 1;
      return "csrf-token";
    },
    fetchImpl: async () => {
      fetchCalls += 1;
      return new Response("{}", {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });
  const request = {
    sessionId: "session.1",
    connectionGeneration: 1,
    runtimeGeneration: 1,
    displayedRevision: 1,
    semanticDigest: D1,
  };
  Object.defineProperty(request, "operationId", {
    enumerable: true,
    get() {
      getterCalls += 1;
      return "operation.hostile";
    },
  });

  await assert.rejects(
    transport.request("operation/request", request),
    (error) => error.code === ERROR_CODES.INVALID_INPUT,
  );
  assert.equal(getterCalls, 0);
  assert.equal(csrfCalls, 0);
  assert.equal(fetchCalls, 0);
});

test("reconnect reconciliation is capped to one concurrent batch", async () => {
  const storage = new MemoryStorage();
  const store = new LocalStoragePendingStore({ storage, key: "hepta.pending.batch" });
  let connection = 0;
  let active = 0;
  let maxActive = 0;
  let reconcileCalls = 0;
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const transport = {
    async connect(input) {
      connection += 1;
      return {
        authenticated: true,
        sessionId: `session.${connection}`,
        connectionGeneration: connection,
        protocolVersion: input.protocolVersion,
      };
    },
    async request() { throw new Error("ack lost"); },
    async reconcile() {
      reconcileCalls += 1;
      active += 1;
      maxActive = Math.max(maxActive, active);
      await gate;
      active -= 1;
      return null;
    },
    async close() {},
  };
  const first = new RuntimeClient({
    transport,
    pendingStore: store,
    setTimer: frozenTimer,
    clearTimer: () => {},
  });
  await connectWithSnapshot(first);
  for (let index = 0; index < 12; index += 1) {
    const ack = await first.submitRequest({
      operationId: `operation.batch.${index}`,
      subjectId: "runtime.agentd",
      action: "request_retry",
      expectedRevision: 4,
      displayedView: displayedViewBinding(),
    });
    assert.equal(ack.status, "indeterminate");
  }

  const second = new RuntimeClient({
    transport,
    pendingStore: store,
    setTimer: frozenTimer,
    clearTimer: () => {},
  });
  const reconnect = second.connect({
    endpointId: "runtime.1",
    protocolVersion: 1,
    manifestDigest: D1,
  });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(reconcileCalls, 8);
  assert.equal(maxActive, 8);
  release();
  const session = await reconnect;
  assert.equal(session.pendingReconciliation, 12);
});

test("automatic reconnect does not retry recovery-required operations", async () => {
  const storage = new MemoryStorage();
  const store = new LocalStoragePendingStore({ storage, key: "hepta.pending.recovery" });
  store.save([
    {
      method: "operation/request",
      operationId: "operation.manual-only",
      semanticDigest: D1,
      originSessionId: "session.old",
      originConnectionGeneration: 1,
      runtimeGeneration: 7,
      displayedRevision: 9,
      accepted: true,
      status: "indeterminate",
      createdAtMs: 0,
      reconcileAttempts: 64,
      nextReconcileAtMs: 0,
      recoveryRequired: true,
    },
  ]);
  let reconcileCalls = 0;
  const transport = {
    async connect(input) {
      return {
        authenticated: true,
        sessionId: "session.new",
        connectionGeneration: 2,
        protocolVersion: input.protocolVersion,
      };
    },
    async request() { assert.fail("mutation must not replay"); },
    async reconcile() {
      reconcileCalls += 1;
      return null;
    },
    async close() {},
  };
  const client = new RuntimeClient({
    transport,
    pendingStore: store,
    clock: () => 1,
    setTimer: frozenTimer,
    clearTimer: () => {},
  });
  const session = await client.connect({
    endpointId: "runtime.1",
    protocolVersion: 1,
    manifestDigest: D2,
  });
  assert.equal(session.recoveryRequired, 1);
  assert.equal(reconcileCalls, 0);

  await client.reconcilePending({ force: true });
  assert.equal(reconcileCalls, 1);
});

test("durable recovery metadata with implausible future clocks requires explicit operator recovery", async () => {
  const storage = new MemoryStorage();
  const store = new LocalStoragePendingStore({
    storage,
    key: "hepta.pending.future-clock",
  });
  store.save([
    {
      method: "operation/request",
      operationId: "operation.future-clock",
      semanticDigest: D1,
      originSessionId: "session.old",
      originConnectionGeneration: 1,
      runtimeGeneration: 7,
      displayedRevision: 9,
      accepted: true,
      status: "indeterminate",
      createdAtMs: 10_000_000,
      reconcileAttempts: 1,
      nextReconcileAtMs: 10_001_000,
      recoveryRequired: false,
    },
  ]);
  let reconcileCalls = 0;
  const transport = {
    async connect(input) {
      return {
        authenticated: true,
        sessionId: "session.new",
        connectionGeneration: 2,
        protocolVersion: input.protocolVersion,
      };
    },
    async request() { assert.fail("mutation must not replay"); },
    async reconcile() {
      reconcileCalls += 1;
      return null;
    },
    async close() {},
  };
  const client = new RuntimeClient({
    transport,
    pendingStore: store,
    clock: () => 1_000,
    setTimer: frozenTimer,
    clearTimer: () => {},
  });

  const session = await client.connect({
    endpointId: "runtime.1",
    protocolVersion: 1,
    manifestDigest: D2,
  });
  assert.equal(session.recoveryRequired, 1);
  assert.equal(reconcileCalls, 0);

  await client.reconcilePending({ force: true });
  assert.equal(reconcileCalls, 1);
});

test("transport timeout remains active through response body streaming", async () => {
  const transport = new SameOriginHttpTransport({
    origin: "https://control.example",
    timeoutMs: 5,
    fetchImpl: async (_url, options) =>
      new Response(
        new ReadableStream({
          start(controller) {
            options.signal?.addEventListener("abort", () => controller.error(new Error("aborted")), {
              once: true,
            });
          },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
  });
  await assert.rejects(
    transport.readSnapshot(),
    (error) => error.code === ERROR_CODES.BACKEND_UNAVAILABLE,
  );
});

test("bootstrap timeout covers response body streaming", async () => {
  await assert.rejects(
    loadBrowserBootstrap({
      origin: "https://control.example",
      timeoutMs: 5,
      fetchImpl: async (_url, options) =>
        new Response(
          new ReadableStream({
            start(controller) {
              options.signal?.addEventListener("abort", () => controller.error(new Error("aborted")), {
                once: true,
              });
            },
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
    }),
    (error) => error.code === ERROR_CODES.BACKEND_UNAVAILABLE,
  );
});

test("close invalidates an in-flight connect before it can become current", async () => {
  let releaseConnect;
  const gate = new Promise((resolve) => { releaseConnect = resolve; });
  const transport = {
    async connect(input) {
      await gate;
      return {
        authenticated: true,
        sessionId: "session.late",
        connectionGeneration: 1,
        protocolVersion: input.protocolVersion,
      };
    },
    async request() { assert.fail("request should not run"); },
    async reconcile() { return null; },
    async close() {},
  };
  const client = new RuntimeClient({
    transport,
    setTimer: frozenTimer,
    clearTimer: () => {},
  });
  const connecting = client.connect({
    endpointId: "runtime.1",
    protocolVersion: 1,
    manifestDigest: D1,
  });
  await new Promise((resolve) => setImmediate(resolve));
  await client.close();
  releaseConnect();
  await assert.rejects(
    connecting,
    (error) => error.code === ERROR_CODES.PROTOCOL_VIOLATION,
  );
  assert.throws(
    () => client.readView(),
    (error) => error.code === ERROR_CODES.NOT_CONNECTED,
  );
});

test("post-dispatch persistence failure is visible in the returned acknowledgement", async () => {
  let saves = 0;
  const store = {
    load: () => [],
    save: () => {
      saves += 1;
      if (saves >= 3) throw new Error("storage unavailable");
    },
  };
  const transport = {
    async connect(input) {
      return {
        authenticated: true,
        sessionId: "session.1",
        connectionGeneration: 1,
        protocolVersion: input.protocolVersion,
      };
    },
    async request(method, input) {
      return {
        accepted: true,
        method,
        sessionId: input.sessionId,
        connectionGeneration: input.connectionGeneration,
        runtimeGeneration: input.runtimeGeneration,
        operationId: input.operationId,
        semanticDigest: input.semanticDigest,
      };
    },
    async reconcile() { return null; },
    async close() {},
  };
  const client = new RuntimeClient({
    transport,
    pendingStore: store,
    setTimer: frozenTimer,
    clearTimer: () => {},
  });
  await connectWithSnapshot(client);
  const acknowledgement = await client.submitRequest({
    operationId: "operation.persist-after-dispatch",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: 4,
    displayedView: displayedViewBinding(),
  });
  assert.equal(acknowledgement.status, "indeterminate");
  assert.equal(acknowledgement.recoveryRequired, true);
  assert.equal(acknowledgement.errorCode, ERROR_CODES.PERSISTENCE_UNAVAILABLE);
  assert.equal(client.readView().recoveryRequired, 1);
});

test("age-triggered recoveryRequired is durably recorded on reconnect", async () => {
  const storage = new MemoryStorage();
  const store = new LocalStoragePendingStore({ storage, key: "hepta.pending.age" });
  store.save([
    {
      method: "operation/request",
      operationId: "operation.aged",
      semanticDigest: D1,
      originSessionId: "session.old",
      originConnectionGeneration: 1,
      runtimeGeneration: 7,
      displayedRevision: 9,
      accepted: true,
      status: "indeterminate",
      createdAtMs: 0,
      reconcileAttempts: 0,
      nextReconcileAtMs: 0,
      recoveryRequired: false,
    },
  ]);
  let reconcileCalls = 0;
  const client = new RuntimeClient({
    transport: {
      async connect(input) {
        return {
          authenticated: true,
          sessionId: "session.new",
          connectionGeneration: 2,
          protocolVersion: input.protocolVersion,
        };
      },
      async request() { assert.fail("mutation must not replay"); },
      async reconcile() { reconcileCalls += 1; return null; },
      async close() {},
    },
    pendingStore: store,
    clock: () => 24 * 60 * 60 * 1000 + 1,
    setTimer: frozenTimer,
    clearTimer: () => {},
  });
  const session = await client.connect({
    endpointId: "runtime.1",
    protocolVersion: 1,
    manifestDigest: D2,
  });
  assert.equal(session.recoveryRequired, 1);
  assert.equal(reconcileCalls, 0);
  assert.equal(store.load()[0].recoveryRequired, true);
});

test("automated reconciliation preserves persistence failure error truth", async () => {
  let saves = 0;
  const store = {
    load: () => [],
    save: () => {
      saves += 1;
      if (saves >= 4) throw new Error("delete persistence failed");
    },
  };
  let terminal = false;
  const transport = {
    async connect(input) {
      return {
        authenticated: true,
        sessionId: "session.1",
        connectionGeneration: 1,
        protocolVersion: input.protocolVersion,
      };
    },
    async request(method, input) {
      return {
        accepted: true,
        method,
        sessionId: input.sessionId,
        connectionGeneration: input.connectionGeneration,
        runtimeGeneration: input.runtimeGeneration,
        operationId: input.operationId,
        semanticDigest: input.semanticDigest,
      };
    },
    async reconcile(query) {
      if (!terminal) return null;
      return {
        ...query,
        status: "succeeded",
        terminalObserved: true,
        outcomeDigest: D3,
      };
    },
    async close() {},
  };
  const client = new RuntimeClient({
    transport,
    pendingStore: store,
    clock: () => 10_000,
    setTimer: frozenTimer,
    clearTimer: () => {},
  });
  await connectWithSnapshot(client);
  const acknowledgement = await client.submitRequest({
    operationId: "operation.persist-terminal",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: 4,
    displayedView: displayedViewBinding(),
  });
  assert.equal(acknowledgement.status, "pending");
  terminal = true;
  await client.reconcilePending({ force: true });
  const retry = await client.submitRequest({
    operationId: "operation.persist-terminal",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: 4,
    displayedView: displayedViewBinding(),
  });
  assert.equal(retry.status, "indeterminate");
  assert.equal(retry.recoveryRequired, true);
  assert.equal(retry.errorCode, ERROR_CODES.PERSISTENCE_UNAVAILABLE);
});

test("displayed-view and stop-scope accessors fail without invoking getters", async () => {
  let requestCalls = 0;
  const client = new RuntimeClient({
    transport: {
      async connect(input) {
        return {
          authenticated: true,
          sessionId: "session.1",
          connectionGeneration: 1,
          protocolVersion: input.protocolVersion,
        };
      },
      async request() { requestCalls += 1; return {}; },
      async reconcile() { return null; },
      async close() {},
    },
    setTimer: frozenTimer,
    clearTimer: () => {},
  });
  await connectWithSnapshot(client);

  let displayedGetterCalls = 0;
  const operation = {
    operationId: "operation.hostile-view",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: 4,
  };
  Object.defineProperty(operation, "displayedView", {
    enumerable: true,
    get() {
      displayedGetterCalls += 1;
      return displayedViewBinding();
    },
  });
  await assert.rejects(
    client.submitRequest(operation),
    (error) => error.code === ERROR_CODES.INVALID_INPUT,
  );
  assert.equal(displayedGetterCalls, 0);

  let scopeGetterCalls = 0;
  const stop = {
    operationId: "stop.hostile-scope",
    displayedView: displayedViewBinding(),
  };
  Object.defineProperty(stop, "scope", {
    enumerable: true,
    get() {
      scopeGetterCalls += 1;
      return { scopeKind: "runtime", targetId: "runtime.agentd" };
    },
  });
  await assert.rejects(
    client.requestStop(stop),
    (error) => error.code === ERROR_CODES.INVALID_INPUT,
  );
  assert.equal(scopeGetterCalls, 0);
  assert.equal(requestCalls, 0);
});

test("failed initial browser runtime install releases its durable writer lease", async () => {
  const document = new FakeDocument();
  const root = new FakeElement("div", document);
  document.body = new FakeElement("body", document);
  document.querySelector = (selector) => (selector === "#app" ? root : null);
  document.visibilityState = "visible";
  document.addEventListener = () => {};
  document.removeEventListener = () => {};
  const held = new Set();
  const lockManager = {
    async request(name, options, callback) {
      assert.deepEqual(options, { mode: "exclusive", ifAvailable: true });
      if (held.has(name)) return callback(null);
      held.add(name);
      try {
        return await callback({ name, mode: "exclusive" });
      } finally {
        held.delete(name);
      }
    },
  };
  const window = {
    location: { origin: "https://control.example" },
    setInterval() { assert.fail("failed startup must not start snapshot polling"); },
    clearInterval() {},
    addEventListener() {},
    removeEventListener() {},
  };
  let connectCalls = 0;
  const fetchImpl = async (url) => {
    const path = new URL(url).pathname;
    if (path === "/api/ui-control/bootstrap") {
      return new Response(
        JSON.stringify({
          endpointId: "runtime.1",
          protocolVersion: 1,
          manifestDigest: D1,
          basePath: "/api/ui-control",
          persistenceNamespace: "principal.a",
          snapshotPollMs: 2_000,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    if (path === "/api/ui-control/csrf") {
      return new Response(JSON.stringify({ token: "csrf" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (path === "/api/ui-control/connect") {
      connectCalls += 1;
      return new Response(JSON.stringify({ error: "unavailable" }), {
        status: 503,
        headers: { "content-type": "application/json" },
      });
    }
    assert.fail(`unexpected startup request ${path}`);
  };

  await assert.rejects(
    startControlPlane({
      document,
      window,
      storage: new MemoryStorage(),
      fetchImpl,
      lockManager,
    }),
    (error) => error.code === ERROR_CODES.BACKEND_UNAVAILABLE,
  );
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(connectCalls, 1);
  assert.equal(held.size, 0);
});

test("failed persistence-domain switch keeps the old lease recoverable and releases the candidate", async () => {
  const document = new FakeDocument();
  const root = new FakeElement("div", document);
  document.body = new FakeElement("body", document);
  document.querySelector = (selector) => (selector === "#app" ? root : null);
  document.visibilityState = "visible";
  document.addEventListener = () => {};
  document.removeEventListener = () => {};
  const held = new Set();
  const lockManager = {
    async request(name, options, callback) {
      assert.deepEqual(options, { mode: "exclusive", ifAvailable: true });
      if (held.has(name)) return callback(null);
      held.add(name);
      try {
        return await callback({ name, mode: "exclusive" });
      } finally {
        held.delete(name);
      }
    },
  };
  let intervalId = 0;
  const windowListeners = new Map();
  const window = {
    location: { origin: "https://control.example" },
    setInterval() { intervalId += 1; return intervalId; },
    clearInterval() {},
    addEventListener(name, listener) { windowListeners.set(name, listener); },
    removeEventListener(name) { windowListeners.delete(name); },
  };
  let bootstrapCalls = 0;
  let connectCalls = 0;
  let failFirstDomainBConnect = true;
  let activeSession = null;
  let activeGeneration = 0;
  let heldRequestGate = null;
  let heldRequestStartedResolve = null;
  let requestCalls = 0;
  let reconcileCalls = 0;
  const fetchImpl = async (url, options = {}) => {
    const path = new URL(url).pathname;
    if (path === "/api/ui-control/bootstrap") {
      bootstrapCalls += 1;
      const domain = bootstrapCalls === 1 ? "principal.a" : "principal.b";
      return new Response(
        JSON.stringify({
          endpointId: "runtime.1",
          protocolVersion: 1,
          manifestDigest: D1,
          basePath: "/api/ui-control",
          persistenceNamespace: domain,
          snapshotPollMs: 2_000,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    if (path === "/api/ui-control/csrf") {
      return new Response(JSON.stringify({ token: "csrf" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (path === "/api/ui-control/connect") {
      connectCalls += 1;
      if (connectCalls > 1 && failFirstDomainBConnect) {
        failFirstDomainBConnect = false;
        return new Response(JSON.stringify({ error: "unavailable" }), {
          status: 503,
          headers: { "content-type": "application/json" },
        });
      }
      activeGeneration += 1;
      activeSession = `session.${activeGeneration}`;
      return new Response(
        JSON.stringify({
          authenticated: true,
          sessionId: activeSession,
          connectionGeneration: activeGeneration,
          protocolVersion: 1,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    if (path === "/api/ui-control/snapshot") {
      return new Response(
        JSON.stringify({
          sessionId: activeSession,
          connectionGeneration: activeGeneration,
          generation: 7 + activeGeneration,
          revision: 9 + activeGeneration,
          digest: D2,
          modules: [
            {
              moduleId: "runtime.agentd",
              status: "ready",
              revision: 4 + activeGeneration,
              digest: D3,
            },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    if (path === "/api/ui-control/request") {
      requestCalls += 1;
      const body = JSON.parse(options.body);
      heldRequestStartedResolve?.();
      if (heldRequestGate) {
        await heldRequestGate;
        heldRequestGate = null;
        heldRequestStartedResolve = null;
      }
      return new Response(
        JSON.stringify({
          accepted: true,
          method: body.method,
          sessionId: body.request.sessionId,
          connectionGeneration: body.request.connectionGeneration,
          runtimeGeneration: body.request.runtimeGeneration,
          operationId: body.request.operationId,
          semanticDigest: body.request.semanticDigest,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    if (path === "/api/ui-control/reconcile") {
      reconcileCalls += 1;
      return new Response("null", {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (path === "/api/ui-control/close") {
      return new Response(JSON.stringify({ closed: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    assert.fail(`unexpected recovery request ${path}`);
  };

  const control = await startControlPlane({
    document,
    window,
    storage: new MemoryStorage(),
    fetchImpl,
    lockManager,
  });
  assert.ok(control);
  assert.equal(held.size, 1);
  const oldLeaseName = [...held][0];

  await assert.rejects(
    control.reconnect("switch domain"),
    (error) => error.code === ERROR_CODES.BACKEND_UNAVAILABLE,
  );
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual([...held], [oldLeaseName]);

  await control.reconnect("retry domain switch");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(held.size, 1);
  assert.notEqual([...held][0], oldLeaseName);
  const domainBLeaseName = [...held][0];

  let finishHeldRequest;
  heldRequestGate = new Promise((resolve) => { finishHeldRequest = resolve; });
  const heldRequestStarted = new Promise((resolve) => { heldRequestStartedResolve = resolve; });
  const activeView = control.client.readView();
  const submission = control.client.submitRequest({
    operationId: "operation.bfcache-drain",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: activeView.modules[0].revision,
    displayedView: {
      sessionId: activeView.sessionId,
      connectionGeneration: activeView.connectionGeneration,
      generation: activeView.generation,
      revision: activeView.revision,
      digest: activeView.digest,
    },
  });
  await heldRequestStarted;
  assert.equal(requestCalls, 1);

  const pageHide = windowListeners.get("pagehide");
  const pageShow = windowListeners.get("pageshow");
  assert.equal(typeof pageHide, "function");
  assert.equal(typeof pageShow, "function");
  pageHide();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual([...held], [domainBLeaseName]);

  finishHeldRequest();
  const acknowledgement = await submission;
  assert.equal(acknowledgement.accepted, true);
  for (let index = 0; index < 20 && held.size !== 0; index += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
  assert.equal(held.size, 0);

  const beforeResumeConnect = connectCalls;
  pageShow({ persisted: true });
  for (let index = 0; index < 40 && (held.size !== 1 || connectCalls === beforeResumeConnect); index += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
  assert.equal(held.size, 1);
  assert.equal([...held][0], domainBLeaseName);
  assert.ok(connectCalls > beforeResumeConnect);
  assert.equal(requestCalls, 1);
  assert.ok(reconcileCalls >= 1);

  await control.dispose();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(held.size, 0);
});

test("browser writer lease permits only one durable writer for a persistence domain", async () => {
  const held = new Set();
  const lockManager = {
    async request(name, options, callback) {
      assert.deepEqual(options, { mode: "exclusive", ifAvailable: true });
      if (held.has(name)) return callback(null);
      held.add(name);
      try {
        return await callback({ name, mode: "exclusive" });
      } finally {
        held.delete(name);
      }
    },
  };

  const first = await acquireControlPlaneLease({
    lockManager,
    name: "hepta.ui.control.writer.test-domain",
  });
  assert.ok(first);
  const second = await acquireControlPlaneLease({
    lockManager,
    name: "hepta.ui.control.writer.test-domain",
  });
  assert.equal(second, null);

  first.release();
  await new Promise((resolve) => setImmediate(resolve));
  const third = await acquireControlPlaneLease({
    lockManager,
    name: "hepta.ui.control.writer.test-domain",
  });
  assert.ok(third);
  third.release();
});

test("browser writer lease fails closed when Web Locks are unavailable", async () => {
  await assert.rejects(
    acquireControlPlaneLease({
      lockManager: null,
      name: "hepta.ui.control.writer.test-domain",
    }),
    (error) => error.code === ERROR_CODES.PERSISTENCE_UNAVAILABLE,
  );
});


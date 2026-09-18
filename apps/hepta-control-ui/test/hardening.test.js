import assert from "node:assert/strict";
import test from "node:test";

import { ControlPlaneApp } from "../src/browser-app.js";
import { loadBrowserBootstrap } from "../src/browser-host.js";
import { SameOriginHttpTransport } from "../src/http-transport.js";
import { LocalStoragePendingStore } from "../src/pending-store.js";
import { ERROR_CODES } from "../src/protocol.js";
import { RuntimeClient } from "../src/runtime-client.js";

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

test("in-flight acknowledgement is verified against immutable request provenance after reconnect", async () => {
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
    displayedRevision: 9,
  });
  const started = await requestStarted;
  await client.close();
  await client.connect({ endpointId: "runtime.1", protocolVersion: 1, manifestDigest: D1 });
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
  assert.equal(ack.accepted, true);
  assert.equal(ack.originSessionId, "session.1");
  assert.equal(client.readView().pending, 1);
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
    displayedRevision: 9,
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
    client.submitRequest({ operationId: "operation.no-store", subjectId: "runtime.agentd", action: "request_retry", expectedRevision: 4, displayedRevision: 9 }),
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
  return Object.freeze({ stale: false, generation: 7, revision: 9, pending: 0, indeterminate: 0, recoveryRequired: 0, modules: Object.freeze([Object.freeze({ moduleId: "runtime.agentd", status: "ready", revision: 4, digest: D3, ready: true })]) });
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
      displayedRevision: 9,
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


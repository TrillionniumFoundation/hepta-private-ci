import assert from "node:assert/strict";
import test from "node:test";

import { ControlPlaneApp } from "../src/browser-app.js";
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

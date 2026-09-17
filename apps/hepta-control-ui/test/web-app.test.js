import assert from "node:assert/strict";
import test from "node:test";

import { ControlPlaneWebApp } from "../src/web-app.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);

class FakeElement {
  constructor(tagName, ownerDocument) {
    this.tagName = tagName.toUpperCase();
    this.ownerDocument = ownerDocument;
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.textContent = "";
    this.disabled = false;
    this.type = "";
    this.id = "";
    this.focused = false;
  }

  append(...nodes) {
    this.children.push(...nodes);
  }

  appendChild(node) {
    this.children.push(node);
    return node;
  }

  replaceChildren(...nodes) {
    this.children = [...nodes];
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  focus() {
    this.focused = true;
  }

  addEventListener(name, listener) {
    const listeners = this.listeners.get(name) ?? [];
    listeners.push(listener);
    this.listeners.set(name, listeners);
  }

  async click() {
    for (const listener of this.listeners.get("click") ?? []) {
      await listener({ type: "click", target: this });
    }
  }
}

class FakeDocument {
  createElement(tagName) {
    return new FakeElement(tagName, this);
  }
}

function flatten(root) {
  const result = [];
  function visit(node) {
    result.push(node);
    for (const child of node.children ?? []) {
      visit(child);
    }
  }
  visit(root);
  return result;
}

function allText(root) {
  return flatten(root)
    .map((node) => node.textContent)
    .filter(Boolean)
    .join("\n");
}

function fakeTransport() {
  const calls = [];
  let subscription = null;
  return {
    calls,
    get subscription() {
      return subscription;
    },
    async connect(input) {
      calls.push(["connect", input]);
      return {
        authenticated: true,
        sessionId: "session.1",
        connectionGeneration: 1,
        protocolVersion: input.protocolVersion,
      };
    },
    async request(method, input) {
      calls.push([method, input]);
      return {
        accepted: true,
        operationId: input.operationId,
        semanticDigest: input.semanticDigest,
        requestKind: input.requestKind,
        originSessionId: input.sessionId,
        originConnectionGeneration: input.connectionGeneration,
        runtimeGeneration: input.runtimeGeneration,
      };
    },
    async close(input) {
      calls.push(["close", input]);
    },
    async subscribe(value) {
      subscription = value;
      calls.push(["subscribe", { sessionId: value.sessionId }]);
      return async () => {
        calls.push(["unsubscribe", { sessionId: value.sessionId }]);
      };
    },
  };
}

test("web app renders redacted runtime state and routes confirmed controls through RuntimeClient", async () => {
  const document = new FakeDocument();
  const root = new FakeElement("div", document);
  const io = fakeTransport();
  const confirmations = [];
  const app = new ControlPlaneWebApp({
    root,
    transport: io,
    endpointManifest: {
      endpointId: "runtime.1",
      protocolVersion: 1,
      manifestDigest: D1,
    },
    confirmAction: async (action) => {
      confirmations.push(action);
      return true;
    },
    operationIdFactory: () => "operation.web.1",
  });

  await app.start();
  assert.match(allText(root), /Runtime view is stale/);

  io.subscription.onSnapshot({
    sessionId: "session.1",
    connectionGeneration: 1,
    generation: 7,
    revision: 9,
    digest: D2,
    modules: [
      {
        moduleId: "runtime.agentd",
        status: "ready",
        revision: 9,
        digest: D3,
        secret: "must-not-leak",
        providerPayload: { token: "must-not-leak" },
      },
    ],
  });

  const rendered = allText(root);
  assert.match(rendered, /runtime.agentd/);
  assert.doesNotMatch(rendered, /must-not-leak/);
  const buttons = flatten(root).filter((node) => node.tagName === "BUTTON");
  assert.equal(buttons.length, 5);
  assert.equal(buttons.every((node) => node.disabled === false), true);

  const retry = buttons.find((node) =>
    node.textContent.startsWith("Request retry"),
  );
  await retry.click();
  assert.equal(confirmations.length, 1);
  const [, payload] = io.calls.find(
    ([method]) => method === "operation/request",
  );
  assert.equal(payload.intent.operationId, "operation.web.1");
  assert.equal(payload.intent.subjectId, "runtime.agentd");
  assert.equal(payload.intent.expectedRevision, 9);
  assert.match(payload.semanticDigest, /^[0-9a-f]{64}$/);

  await app.stop();
  assert.match(allText(root), /Disconnected/);
});

test("web app preserves indeterminate state and focuses recoverable errors", async () => {
  const document = new FakeDocument();
  const root = new FakeElement("div", document);
  const io = fakeTransport();
  const app = new ControlPlaneWebApp({
    root,
    transport: io,
    endpointManifest: {
      endpointId: "runtime.1",
      protocolVersion: 1,
      manifestDigest: D1,
    },
    confirmAction: async () => true,
    operationIdFactory: () => "operation.web.timeout",
  });

  await app.start();
  io.subscription.onSnapshot({
    sessionId: "session.1",
    connectionGeneration: 1,
    generation: 7,
    revision: 9,
    digest: D2,
    modules: [
      {
        moduleId: "runtime.agentd",
        status: "ready",
        revision: 9,
        digest: D3,
      },
    ],
  });

  io.request = async (method, input) => {
    io.calls.push([method, input]);
    throw new Error("response lost after write");
  };
  const retry = flatten(root)
    .filter((node) => node.tagName === "BUTTON")
    .find((node) => node.textContent.startsWith("Request retry"));
  await retry.click();

  const rendered = allText(root);
  assert.match(rendered, /indeterminate and requires reconciliation/);
  assert.match(rendered, /1 operation pending; 1 indeterminate/);
  assert.match(rendered, /BACKEND_UNAVAILABLE/);
  const alert = flatten(root).find(
    (node) => node.attributes.get("role") === "alert",
  );
  assert.equal(alert.focused, true);
  assert.equal(
    flatten(root).filter((node) => node.tagName === "BUTTON").length,
    5,
  );
});

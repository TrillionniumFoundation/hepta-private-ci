import assert from "node:assert/strict";
import test from "node:test";

import { ControlPlaneApp, buildControlViewModel } from "../src/browser-app.js";

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
  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }
  append(...children) {
    this.children.push(...children);
  }
  replaceChildren(...children) {
    this.children = [...children];
  }
  addEventListener(name, listener) {
    this.listeners.set(name, listener);
  }
}

class FakeDocument {
  createElement(tagName) {
    return new FakeElement(tagName, this);
  }
}

function allElements(root) {
  const result = [];
  const visit = (element) => {
    result.push(element);
    for (const child of element.children) visit(child);
  };
  visit(root);
  return result;
}

function sampleView({ stale = false } = {}) {
  return Object.freeze({
    stale,
    generation: stale ? null : 7,
    revision: stale ? null : 9,
    pending: 2,
    indeterminate: 1,
    modules: Object.freeze([
      Object.freeze({
        moduleId: "runtime.agentd",
        status: "ready",
        revision: 4,
        digest: "a".repeat(64),
        ready: true,
        secret: "must-not-render",
      }),
    ]),
  });
}

test("view model re-projects only display-safe module fields", () => {
  const model = buildControlViewModel(sampleView());
  assert.deepEqual(model.modules[0], {
    moduleId: "runtime.agentd",
    status: "ready",
    revision: 4,
    digest: "a".repeat(64),
    ready: true,
  });
  assert.equal("secret" in model.modules[0], false);
  assert.equal(model.canMutate, true);
});

test("stale views disable all mutating browser controls", () => {
  const document = new FakeDocument();
  const root = new FakeElement("div", document);
  const client = {
    readView: () => sampleView({ stale: true }),
    submitRequest: async () => assert.fail("submitRequest should not run"),
    requestStop: async () => assert.fail("requestStop should not run"),
  };
  const app = new ControlPlaneApp({ root, client });
  app.render();
  const buttons = allElements(root).filter((element) => element.tagName === "button");
  assert.equal(buttons.length, 5);
  assert.equal(buttons.every((button) => button.disabled), true);
});

test("confirmed module action binds target revision and displayed revision separately", async () => {
  const document = new FakeDocument();
  const root = new FakeElement("div", document);
  const submissions = [];
  const confirmations = [];
  const client = {
    readView: () => sampleView(),
    async submitRequest(request) {
      submissions.push(request);
      return { operationId: request.operationId, status: "pending" };
    },
    async requestStop() {
      assert.fail("requestStop should not run");
    },
  };
  const app = new ControlPlaneApp({
    root,
    client,
    operationIdFactory: () => "operation.browser.1",
    confirmAction: async (confirmation) => {
      confirmations.push(confirmation);
      return true;
    },
  });
  app.render();
  const retry = allElements(root).find(
    (element) => element.tagName === "button" && element.textContent.startsWith("Retry "),
  );
  await retry.listeners.get("click")();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(confirmations.length, 1);
  assert.deepEqual(submissions[0], {
    operationId: "operation.browser.1",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: 4,
    displayedRevision: 9,
  });
});

test("indeterminate acknowledgement remains announced after rerender", async () => {
  const document = new FakeDocument();
  const root = new FakeElement("div", document);
  const client = {
    readView: () => sampleView(),
    async submitRequest(request) {
      return { operationId: request.operationId, status: "indeterminate" };
    },
    async requestStop() {
      assert.fail("requestStop should not run");
    },
  };
  const app = new ControlPlaneApp({
    root,
    client,
    operationIdFactory: () => "operation.browser.indeterminate",
    confirmAction: async () => true,
  });
  app.render();
  const retry = allElements(root).find(
    (element) => element.tagName === "button" && element.textContent.startsWith("Retry "),
  );
  retry.listeners.get("click")();
  await new Promise((resolve) => setImmediate(resolve));
  const alert = allElements(root).find(
    (element) => element.attributes.get("role") === "alert",
  );
  assert.ok(alert);
  assert.match(alert.textContent, /indeterminate/);
});

test("browser request-construction failures are announced instead of escaping click handlers", async () => {
  const document = new FakeDocument();
  const root = new FakeElement("div", document);
  let submissions = 0;
  const client = {
    readView: () => sampleView(),
    async submitRequest() {
      submissions += 1;
      return { operationId: "unexpected", status: "pending" };
    },
    async requestStop() {
      submissions += 1;
      return { operationId: "unexpected-stop", status: "pending" };
    },
  };
  const app = new ControlPlaneApp({
    root,
    client,
    operationIdFactory: () => {
      throw new Error("random source unavailable");
    },
    confirmAction: async () => true,
  });
  app.render();
  const retry = allElements(root).find(
    (element) => element.tagName === "button" && element.textContent.startsWith("Retry "),
  );
  retry.listeners.get("click")();
  await new Promise((resolve) => setImmediate(resolve));
  const alert = allElements(root).find(
    (element) => element.attributes.get("role") === "alert",
  );
  assert.ok(alert);
  assert.match(alert.textContent, /Request construction failed/);
  assert.equal(submissions, 0);
});

test("browser exposes bounded read-only recovery for unresolved operations", async () => {
  const document = new FakeDocument();
  const root = new FakeElement("div", document);
  let reconcileCalls = 0;
  const client = {
    readView: () => Object.freeze({ ...sampleView(), recoveryRequired: 1 }),
    async submitRequest() { assert.fail("mutation should not run"); },
    async requestStop() { assert.fail("stop should not run"); },
    async reconcilePending(input) {
      reconcileCalls += 1;
      assert.deepEqual(input, { force: true });
      return {
        pending: 2,
        indeterminate: 1,
        recoveryRequired: 1,
      };
    },
  };
  const app = new ControlPlaneApp({ root, client });
  app.render();
  const reconcile = allElements(root).find(
    (element) =>
      element.tagName === "button" &&
      element.textContent === "Reconcile unresolved operations",
  );
  assert.ok(reconcile);
  reconcile.listeners.get("click")();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(reconcileCalls, 1);
  const alert = allElements(root).find(
    (element) => element.attributes.get("role") === "alert",
  );
  assert.ok(alert);
  assert.match(alert.textContent, /manual recovery required 1/);
});


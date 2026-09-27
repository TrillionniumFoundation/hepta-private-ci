import assert from "node:assert/strict";
import test from "node:test";
import {
  UI_CONTROL_ERROR_CODES,
  UiControlError,
  createControlConsole,
} from "../src/index.js";
import { deferred } from "./helpers.js";

const REQUIRED_IDS = [
  "connection-state",
  "session-state",
  "identity-state",
  "generation-state",
  "revision-state",
  "stale-banner",
  "live-status",
  "error-status",
  "modules-body",
  "target-id",
  "operation-reason",
  "refresh-view",
  "request-start",
  "request-reconcile",
  "request-stop",
  "pending-list",
  "completed-list",
  "confirm-operation",
  "confirm-title",
  "confirm-summary",
  "confirm-submit",
  "confirm-cancel",
];

class FakeElement {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.options = [];
    this.dataset = {};
    this.textContent = "";
    this.value = "";
    this.hidden = false;
    this.disabled = false;
    this.open = false;
  }

  replaceChildren(...children) {
    this.children = [...children];
    this.#refreshOptions();
  }

  append(...children) {
    this.children.push(...children);
    this.#refreshOptions();
  }

  addEventListener() {}

  focus() {}

  showModal() {
    this.open = true;
  }

  close() {
    this.open = false;
  }

  #refreshOptions() {
    this.options = this.children.filter(child => child?.tagName === "OPTION");
    if (!this.value && this.options.length > 0) this.value = this.options[0].value;
  }
}

function createDocument() {
  const elements = new Map(REQUIRED_IDS.map(id => [id, new FakeElement()]));
  return {
    getElementById(id) {
      return elements.get(id) ?? null;
    },
    createElement(tagName) {
      return new FakeElement(tagName);
    },
    createTextNode(value) {
      return { nodeType: 3, textContent: String(value) };
    },
  };
}

function createView() {
  return Object.freeze({
    connected: true,
    authenticated: true,
    sessionId: "session-1",
    identityId: "operator-1",
    connectionGeneration: 1,
    permissionRevision: 1,
    permissions: Object.freeze([
      "hepta://ui.control/runtime.read",
      "hepta://ui.control/runtime.request",
      "hepta://ui.control/runtime.start",
      "hepta://ui.control/runtime.stop",
    ]),
    expiresAt: Date.now() + 60_000,
    stale: false,
    snapshot: Object.freeze({
      generation: 1,
      revision: 1,
      semanticDigest: "a".repeat(64),
      modules: Object.freeze([]),
    }),
    pending: Object.freeze([]),
    pendingCount: 0,
    indeterminateCount: 0,
    completed: Object.freeze([]),
    completedCount: 0,
  });
}

function createClient(counters) {
  const view = createView();
  return {
    readView() {
      return view;
    },
    async refreshView() {
      counters.refresh += 1;
    },
    async recoverPending() {
      counters.recover += 1;
      return Object.freeze([]);
    },
    exportRecoveryState() {
      return Object.freeze({ version: 1, operations: Object.freeze([]) });
    },
    restoreRecoveryState() {},
    async close() {
      counters.close += 1;
    },
  };
}

test("browser console start is single-flight and installs one poller", { concurrency: false }, async t => {
  const gate = deferred();
  const counters = { start: 0, stop: 0, refresh: 0, recover: 0, close: 0 };
  const provider = {
    async start() {
      counters.start += 1;
      await gate.promise;
    },
    subscribe() {
      return () => {};
    },
    stop() {
      counters.stop += 1;
    },
  };
  const originalSetInterval = globalThis.setInterval;
  const originalClearInterval = globalThis.clearInterval;
  let installed = 0;
  let cleared = 0;
  globalThis.setInterval = () => {
    installed += 1;
    return 41;
  };
  globalThis.clearInterval = timer => {
    assert.equal(timer, 41);
    cleared += 1;
  };
  t.after(() => {
    globalThis.setInterval = originalSetInterval;
    globalThis.clearInterval = originalClearInterval;
    gate.resolve();
  });

  const consoleApp = createControlConsole({
    document: createDocument(),
    client: createClient(counters),
    sessionProvider: provider,
    storage: null,
    pollIntervalMs: 250,
  });

  const first = consoleApp.start();
  const second = consoleApp.start();
  assert.equal(counters.start, 1);
  gate.resolve();
  await Promise.all([first, second]);
  await consoleApp.start();

  assert.equal(counters.start, 1);
  assert.equal(counters.refresh, 1);
  assert.equal(counters.recover, 1);
  assert.equal(installed, 1);

  await consoleApp.destroy();
  assert.equal(counters.stop, 1);
  assert.equal(counters.close, 1);
  assert.equal(cleared, 1);
  await assert.rejects(
    consoleApp.start(),
    error =>
      error instanceof UiControlError &&
      error.code === UI_CONTROL_ERROR_CODES.ABORTED,
  );
});

test("destroy fences a browser console start that is still in flight", { concurrency: false }, async t => {
  const gate = deferred();
  const counters = { start: 0, stop: 0, refresh: 0, recover: 0, close: 0 };
  const provider = {
    async start() {
      counters.start += 1;
      await gate.promise;
    },
    subscribe() {
      return () => {};
    },
    stop() {
      counters.stop += 1;
    },
  };
  const originalSetInterval = globalThis.setInterval;
  let installed = 0;
  globalThis.setInterval = () => {
    installed += 1;
    return 42;
  };
  t.after(() => {
    globalThis.setInterval = originalSetInterval;
    gate.resolve();
  });

  const consoleApp = createControlConsole({
    document: createDocument(),
    client: createClient(counters),
    sessionProvider: provider,
    storage: null,
    pollIntervalMs: 250,
  });

  const starting = consoleApp.start();
  await consoleApp.destroy();
  gate.resolve();
  await assert.rejects(
    starting,
    error =>
      error instanceof UiControlError &&
      error.code === UI_CONTROL_ERROR_CODES.ABORTED,
  );

  assert.equal(counters.start, 1);
  assert.equal(counters.stop, 1);
  assert.equal(counters.close, 1);
  assert.equal(counters.refresh, 0);
  assert.equal(installed, 0);
});

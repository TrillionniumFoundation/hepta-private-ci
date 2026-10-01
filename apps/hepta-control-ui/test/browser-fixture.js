export class MemoryStorage {
  values = new Map();
  enumerations = 0;
  reads = 0;
  removals = 0;
  get length() { return this.values.size; }
  key(index) { this.enumerations += 1; return [...this.values.keys()][index] ?? null; }
  getItem(key) { this.reads += 1; return this.values.get(key) ?? null; }
  setItem(key, value) { this.values.set(key, value); }
  removeItem(key) { this.removals += 1; this.values.delete(key); }
}

export class SharedLocks {
  tail = Promise.resolve();
  requests = 0;
  reject = false;
  request(name, options, callback) {
    this.requests += 1;
    const task = this.tail.then(() => {
      options.signal?.throwIfAborted();
      if (this.reject) throw new Error("lock denied");
      return callback();
    });
    this.tail = task.catch(() => {});
    return task;
  }
}

export function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

class Element {
  children = [];
  listeners = new Map();
  attributes = new Map();
  value = "";
  disabled = false;
  hidden = false;
  open = false;
  writes = 0;
  replacements = 0;
  #text = "";
  constructor(document, tag) { this.document = document; this.tagName = tag.toUpperCase(); }
  get textContent() { return this.#text + this.children.map(node => node.textContent).join(""); }
  set textContent(value) { this.writes += 1; this.#text = String(value); this.children = []; }
  get options() { return this.children.filter(node => node.tagName === "OPTION"); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.replacements += 1; this.#text = ""; this.children = nodes; }
  setAttribute(name, value) { this.attributes.set(name, value); }
  addEventListener(name, fn) { this.listeners.set(name, fn); }
  async fire(name = "click") {
    return this.listeners.get(name)?.({ currentTarget: this, preventDefault() {} });
  }
  focus() { this.document.activeElement = this; }
  showModal() { this.open = true; }
  close() { this.open = false; }
}

export function createDocument() {
  const ids = ["connection-state", "session-state", "identity-state", "generation-state",
    "revision-state", "stale-banner", "live-status", "error-status", "modules-body",
    "target-id", "operation-reason", "refresh-view", "request-start", "request-reconcile",
    "request-stop", "pending-list", "completed-list", "confirm-operation", "confirm-title",
    "confirm-summary", "confirm-submit", "confirm-cancel"];
  const nodes = new Map();
  const document = {
    activeElement: null, visibilityState: "visible", created: 0,
    getElementById: id => nodes.get(id) ?? null,
    createElement(tag) { this.created += 1; return new Element(this, tag); },
    createTextNode(value) { return { nodeType: 3, textContent: String(value) }; },
  };
  for (const id of ids) nodes.set(id, document.createElement("div"));
  return document;
}

export const operation = (id = "operation-1") => ({
  operationId: id, protocolVersion: "hepta.ui-control.v1", method: "runtime/stop",
  semanticDigest: "a".repeat(64), action: "request_stop", targetId: "runtime.agentd",
  reason: "Maintenance", sessionId: "session-1", connectionGeneration: 1,
  generation: 7, displayedRevision: 12, snapshotDigest: "b".repeat(64),
  state: "submitting", createdAt: 1, updatedAt: 1, auditTraceId: null,
});
export const terminal = id => ({ ...operation(id), state: "terminal", terminalStatus: "succeeded" });
export const storageOptions = (storage = new MemoryStorage(), locks = new SharedLocks()) => ({
  storage, locks, endpoint: "https://console.test/api/ui-control/v1/",
  identityId: "operator-1", protocolVersion: "hepta.ui-control.v1",
});
export function fixture() {
  const document = createDocument();
  const options = storageOptions();
  const view = {
    connected: true, authenticated: true, stale: false, sessionId: "session-1",
    identityId: "operator-1", permissionRevision: 1, connectionGeneration: 1,
    permissions: ["read", "request", "start", "stop"].map(x => `hepta://ui.control/runtime.${x}`),
    snapshot: { generation: 7, revision: 12, semanticDigest: "b".repeat(64),
      modules: [{ id: "runtime.agentd", status: "running", revision: 9, semanticDigest: "c".repeat(64) }] },
    pending: [], completed: [],
  };
  const counters = { mutations: 0, close: 0 };
  const client = {
    readView: () => view,
    async refreshView() {}, async recoverPending() {}, restoreRecoveryState() {},
    setRecoveryPersistence(callback) { this.persistence = callback; },
    async requestStop() { counters.mutations += 1; return operation(); },
    async close() { counters.close += 1; },
  };
  const sessionProvider = { async start() {}, stop() {}, subscribe: () => () => {} };
  return { document, options, view, counters, client, sessionProvider,
    config: { document, client, sessionProvider, storage: options.storage,
      locks: options.locks, recoveryEndpoint: options.endpoint, pollIntervalMs: 60000 } };
}

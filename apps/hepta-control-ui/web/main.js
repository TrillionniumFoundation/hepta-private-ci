import {
  RuntimeClient,
  SameOriginHttpTransport,
  SessionProvider,
  UI_CONTROL_PROTOCOL_VERSION,
  UI_CONTROL_ERROR_CODES,
  createControlConsole,
} from "./src/index.js";

const READINESS_SCHEMA = "hepta.ui-control.readiness.v1";

function createTabId() {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return `tab:${globalThis.crypto.randomUUID()}`;
  }
  const words = new Uint32Array(4);
  globalThis.crypto.getRandomValues(words);
  return `tab:${Array.from(words, word => word.toString(16).padStart(8, "0")).join("")}`;
}

const readiness = {
  schema: READINESS_SCHEMA,
  phase: "booting",
  tabId: createTabId(),
  startedAt: new Date().toISOString(),
  readyAt: null,
  failedAt: null,
  errorCode: null,
  stateOwnership: Object.freeze({
    activeSession: "tab-private",
    selectionAndFocus: "tab-private",
    recoveryRecords: "endpoint-protocol-identity-scoped-cross-tab",
    leaderAndClaims: "scope-scoped-cross-tab",
    credentials: "memory-only-never-broadcast-or-persisted",
  }),
};

Object.defineProperty(globalThis, "__heptaUiControlReadiness", {
  value: readiness,
  writable: false,
  configurable: false,
  enumerable: false,
});
document.documentElement.dataset.uiControlReady = "booting";

function publishReadiness(phase, detail = {}) {
  Object.assign(readiness, detail, { phase });
  document.documentElement.dataset.uiControlReady = phase === "ready" ? "true" : phase;
  const receipt = Object.freeze(JSON.parse(JSON.stringify(readiness)));
  globalThis.dispatchEvent(new CustomEvent(`hepta:ui-control:${phase}`, { detail: receipt }));
  return receipt;
}

const csrfTokenProvider = () =>
  document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || null;

// One composition value binds transport routing and local recovery scope.
const apiBase = new URL("/api/ui-control/v1/", globalThis.location.origin).href;
const transport = new SameOriginHttpTransport({
  baseUrl: apiBase,
  csrfTokenProvider,
  fetchImpl: globalThis.fetch.bind(globalThis),
});
const client = new RuntimeClient({ transport });
const sessionProvider = new SessionProvider({
  client,
  endpointManifest: Object.freeze({
    protocolVersion: UI_CONTROL_PROTOCOL_VERSION,
    client: "hepta-control-ui",
    requestedCapabilities: Object.freeze([
      "runtime.read",
      "runtime.request",
      "runtime.start",
      "runtime.stop",
    ]),
  }),
});
const consoleApp = createControlConsole({ client, sessionProvider, recoveryEndpoint: apiBase });

try {
  await consoleApp.start();
  publishReadiness("ready", { readyAt: new Date().toISOString() });
} catch (error) {
  const code = error && Object.getOwnPropertyDescriptor(error, "code")?.value;
  const errorCode = Object.values(UI_CONTROL_ERROR_CODES).includes(code) ? code : "UI_CONTROL_STARTUP";
  publishReadiness("failed", {
    failedAt: new Date().toISOString(),
    errorCode,
  });
  console.error("ui.control console failed to start", errorCode);
}

window.addEventListener("pagehide", () => {
  consoleApp.destroy().catch(() => {});
});
// A BFCache-restored page must establish a fresh tab-private session and read-only recovery,
// never revive a destroyed controller or replay a mutation.
window.addEventListener("pageshow", event => {
  if (event.persisted) window.location.reload();
});

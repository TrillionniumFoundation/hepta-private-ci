import {
  RuntimeClient,
  SameOriginHttpTransport,
  SessionProvider,
  UI_CONTROL_PROTOCOL_VERSION,
  createControlConsole,
} from "./src/index.js";

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

consoleApp.start().catch(error => {
  console.error("ui.control console failed to start", error);
});

window.addEventListener("pagehide", () => {
  consoleApp.destroy().catch(() => {});
});
// A BFCache-restored page must establish a fresh session and read-only recovery,
// never revive a destroyed controller or replay a mutation.
window.addEventListener("pageshow", event => {
  if (event.persisted) window.location.reload();
});

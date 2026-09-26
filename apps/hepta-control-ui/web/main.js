import {
  RuntimeClient,
  SameOriginHttpTransport,
  SessionProvider,
  UI_CONTROL_PROTOCOL_VERSION,
  createControlConsole,
} from "./src/index.js";

const csrfTokenProvider = () =>
  document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || null;

const transport = new SameOriginHttpTransport({ csrfTokenProvider });
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
const consoleApp = createControlConsole({ client, sessionProvider });

consoleApp.start().catch(error => {
  console.error("ui.control console failed to start", error);
});

window.addEventListener("pagehide", () => {
  consoleApp.destroy().catch(() => {});
});

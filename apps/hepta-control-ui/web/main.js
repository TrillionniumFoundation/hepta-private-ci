import { ControlPlaneWebApp } from "../src/web-app.js";

const root = document.getElementById("app");
const bootstrap = globalThis.__HEPTA_CONTROL_BOOTSTRAP__;

if (bootstrap && root) {
  const app = new ControlPlaneWebApp({
    root,
    transport: bootstrap.transport,
    endpointManifest: bootstrap.endpointManifest,
    confirmAction: bootstrap.confirmAction,
    operationIdFactory: bootstrap.operationIdFactory,
  });
  globalThis.__HEPTA_CONTROL_APP__ = app;
  app.start().catch((error) => {
    root.replaceChildren();
    const main = document.createElement("main");
    const title = document.createElement("h1");
    title.textContent = "Hepta control plane";
    const alert = document.createElement("p");
    alert.setAttribute("role", "alert");
    alert.setAttribute("tabindex", "-1");
    alert.textContent =
      error instanceof Error ? error.message : "Control-plane bootstrap failed";
    main.append(title, alert);
    root.append(main);
    alert.focus();
  });
}

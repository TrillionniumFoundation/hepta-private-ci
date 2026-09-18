import { ControlPlaneApp } from "./browser-app.js";
import { createAccessibleConfirmAction, loadBrowserBootstrap } from "./browser-host.js";
import { SameOriginHttpTransport } from "./http-transport.js";
import { LocalStoragePendingStore } from "./pending-store.js";
import { ERROR_CODES, requireDigest, positiveInteger } from "./protocol.js";
import { RuntimeClient } from "./runtime-client.js";

function boundedPoll(value, fallback) {
  const candidate = value == null ? fallback : value;
  if (!Number.isSafeInteger(candidate) || candidate < 500 || candidate > 60_000) {
    throw new TypeError("snapshotPollMs must be between 500 and 60000 ms");
  }
  return candidate;
}

function renderFatal(root, error) {
  const alert = root.ownerDocument.createElement("div");
  alert.setAttribute("role", "alert");
  alert.setAttribute("aria-live", "assertive");
  alert.textContent = `${error?.code ?? "ERROR"}: ${error?.message ?? "Control plane failed to start"}`;
  root.replaceChildren(alert);
}

export async function startControlPlane({
  document = globalThis.document,
  window = globalThis.window,
  storage = globalThis.localStorage,
  fetchImpl = globalThis.fetch?.bind(globalThis),
  bootstrapUrl = "/api/ui-control/bootstrap",
} = {}) {
  const root = document?.querySelector?.("#app");
  if (!root) throw new TypeError("#app root is required");
  const config = await loadBrowserBootstrap({
    url: bootstrapUrl,
    origin: window.location.origin,
    fetchImpl,
  });
  requireDigest(config.manifestDigest, "manifestDigest");
  positiveInteger(config.protocolVersion, "protocolVersion");
  const pollMs = boundedPoll(config.snapshotPollMs, 2_000);
  const persistenceKey = `hepta.ui.control.pending.${config.persistenceNamespace}`;
  const pendingStore = new LocalStoragePendingStore({ storage, key: persistenceKey });
  const transport = new SameOriginHttpTransport({
    baseUrl: config.basePath,
    origin: window.location.origin,
    fetchImpl,
    timeoutMs: config.requestTimeoutMs ?? 10_000,
  });
  const client = new RuntimeClient({ transport, pendingStore });
  await client.connect({
    endpointId: config.endpointId,
    protocolVersion: config.protocolVersion,
    manifestDigest: config.manifestDigest,
  });
  const app = new ControlPlaneApp({
    root,
    client,
    confirmAction: createAccessibleConfirmAction({ document }),
  });

  let refreshing = false;
  const refresh = async () => {
    if (refreshing) return;
    refreshing = true;
    try {
      const snapshot = await transport.readSnapshot();
      client.applySnapshot(snapshot);
      app.setMutationBlock(null);
      root.setAttribute("data-hepta-ready", "true");
    } catch (error) {
      if (client) {
        try {
          app.setMutationBlock(
            error?.code === ERROR_CODES.UNAUTHENTICATED
              ? "Authenticated runtime session is unavailable."
              : "Runtime snapshot refresh failed.",
          );
        } catch {
          renderFatal(root, error);
        }
      }
      throw error;
    } finally {
      refreshing = false;
    }
  };

  await refresh();
  const timer = window.setInterval(() => void refresh().catch(() => {}), pollMs);
  window.addEventListener("online", () => {
    void client.reconcilePending({ force: true }).catch(() => {});
    void refresh().catch(() => {});
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") void refresh().catch(() => {});
  });
  window.addEventListener("pagehide", () => {
    window.clearInterval(timer);
    void client.close().catch(() => {});
  }, { once: true });

  return Object.freeze({ app, client, transport, refresh });
}

if (typeof document !== "undefined" && typeof window !== "undefined") {
  const root = document.querySelector?.("#app");
  if (root) {
    void startControlPlane().catch((error) => renderFatal(root, error));
  }
}

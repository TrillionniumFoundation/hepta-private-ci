import { ControlPlaneApp } from "./browser-app.js";
import { createAccessibleConfirmAction, loadBrowserBootstrap } from "./browser-host.js";
import { SameOriginHttpTransport } from "./http-transport.js";
import { LocalStoragePendingStore } from "./pending-store.js";
import {
  ERROR_CODES,
  canonicalSha256,
  positiveInteger,
  requireDigest,
  stableId,
} from "./protocol.js";
import { RuntimeClient } from "./runtime-client.js";

const PERSISTENCE_DOMAIN_SCHEMA = "hepta.ui-control.persistence-domain.v1";

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

async function normalizeBootstrap({ url, origin, fetchImpl }) {
  const raw = await loadBrowserBootstrap({ url, origin, fetchImpl });
  const endpointId = stableId(raw.endpointId, "endpointId");
  const protocolVersion = positiveInteger(raw.protocolVersion, "protocolVersion");
  const manifestDigest = requireDigest(raw.manifestDigest, "manifestDigest");
  const persistenceNamespace = stableId(raw.persistenceNamespace, "persistenceNamespace");
  const snapshotPollMs = boundedPoll(raw.snapshotPollMs, 2_000);
  const persistenceDomain = await canonicalSha256({
    schema: PERSISTENCE_DOMAIN_SCHEMA,
    endpointId,
    protocolVersion,
    manifestDigest,
    persistenceNamespace,
    basePath: raw.basePath,
  });
  return Object.freeze({
    ...raw,
    endpointId,
    protocolVersion,
    manifestDigest,
    persistenceNamespace,
    snapshotPollMs,
    persistenceKey: `hepta.ui.control.pending.${persistenceDomain}`,
  });
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

  const confirmAction = createAccessibleConfirmAction({ document });
  let config = null;
  let transport = null;
  let client = null;
  let app = null;
  let timer = null;
  let refreshingPromise = null;
  let recoveryPromise = null;
  let suspensionPromise = Promise.resolve();
  let suspended = false;
  let disposed = false;

  const blockMutations = (reason) => {
    root.setAttribute("data-hepta-ready", "false");
    if (!app) return;
    try {
      app.setMutationBlock(reason);
    } catch (error) {
      renderFatal(root, error);
    }
  };

  const loadConfig = () =>
    normalizeBootstrap({
      url: bootstrapUrl,
      origin: window.location.origin,
      fetchImpl,
    });

  const connectArgs = (value) =>
    Object.freeze({
      endpointId: value.endpointId,
      protocolVersion: value.protocolVersion,
      manifestDigest: value.manifestDigest,
    });

  const installRuntime = async (nextConfig) => {
    const nextStore = new LocalStoragePendingStore({
      storage,
      key: nextConfig.persistenceKey,
    });
    const nextTransport = new SameOriginHttpTransport({
      baseUrl: nextConfig.basePath,
      origin: window.location.origin,
      fetchImpl,
      timeoutMs: nextConfig.requestTimeoutMs ?? 10_000,
    });
    const nextClient = new RuntimeClient({
      transport: nextTransport,
      pendingStore: nextStore,
    });
    await nextClient.connect(connectArgs(nextConfig));
    const nextApp = new ControlPlaneApp({
      root,
      client: nextClient,
      confirmAction,
    });

    config = nextConfig;
    transport = nextTransport;
    client = nextClient;
    app = nextApp;
  };

  const applyCurrentSnapshot = async () => {
    const snapshot = await transport.readSnapshot();
    client.applySnapshot(snapshot);
    app.setMutationBlock(null);
    root.setAttribute("data-hepta-ready", "true");
    return client.readView();
  };

  const stopTimer = () => {
    if (timer !== null) window.clearInterval(timer);
    timer = null;
  };

  const startTimer = () => {
    stopTimer();
    if (disposed || !config) return;
    timer = window.setInterval(() => void refresh().catch(() => {}), config.snapshotPollMs);
  };

  const recoverSession = async (reason = "Runtime session is being re-established.") => {
    if (disposed || suspended) return null;
    if (recoveryPromise) return recoveryPromise;
    recoveryPromise = (async () => {
      blockMutations(reason);
      const nextConfig = await loadConfig();
      const samePersistenceDomain =
        config !== null && nextConfig.persistenceKey === config.persistenceKey;

      if (client && samePersistenceDomain) {
        try {
          await client.close();
        } catch {
          // close is best-effort here; RuntimeClient still clears local session state.
        }
        await client.connect(connectArgs(nextConfig));
        config = nextConfig;
      } else {
        if (client) {
          try {
            await client.close();
          } catch {
            // The old principal/domain mirror remains isolated under its old key.
          }
        }
        await installRuntime(nextConfig);
      }

      const view = await applyCurrentSnapshot();
      startTimer();
      return view;
    })().finally(() => {
      recoveryPromise = null;
    });
    return recoveryPromise;
  };

  const refreshOnce = async () => {
    try {
      return await applyCurrentSnapshot();
    } catch (error) {
      blockMutations(
        error?.code === ERROR_CODES.UNAUTHENTICATED
          ? "Authenticated runtime session is unavailable."
          : "Runtime snapshot refresh failed.",
      );
      if (
        error?.code === ERROR_CODES.UNAUTHENTICATED ||
        error?.code === ERROR_CODES.NOT_CONNECTED
      ) {
        return recoverSession("Authenticated runtime session expired; reconnecting.");
      }
      throw error;
    }
  };

  async function refresh() {
    if (disposed || suspended) return null;
    if (refreshingPromise) return refreshingPromise;
    refreshingPromise = refreshOnce().finally(() => {
      refreshingPromise = null;
    });
    return refreshingPromise;
  }

  await installRuntime(await loadConfig());
  await applyCurrentSnapshot();
  startTimer();

  const onOffline = () => {
    blockMutations("Network connectivity is unavailable.");
  };
  const onOnline = () => {
    void recoverSession("Network connectivity was interrupted; reconnecting.").catch(() => {});
  };
  const onVisibilityChange = () => {
    if (document.visibilityState === "visible") void refresh().catch(() => {});
  };
  const onPageHide = () => {
    suspended = true;
    stopTimer();
    blockMutations("Page is suspended; mutating controls are disabled.");
    suspensionPromise = client ? client.close().catch(() => {}) : Promise.resolve();
  };
  const onPageShow = (event) => {
    if (disposed) return;
    if (event?.persisted === true || timer === null) {
      suspended = false;
      void suspensionPromise
        .then(() => recoverSession("Page session resumed; reconnecting."))
        .catch(() => {});
    }
  };

  window.addEventListener("offline", onOffline);
  window.addEventListener("online", onOnline);
  window.addEventListener("pagehide", onPageHide);
  window.addEventListener("pageshow", onPageShow);
  document.addEventListener("visibilitychange", onVisibilityChange);

  const dispose = async () => {
    if (disposed) return;
    disposed = true;
    suspended = true;
    stopTimer();
    window.removeEventListener?.("offline", onOffline);
    window.removeEventListener?.("online", onOnline);
    window.removeEventListener?.("pagehide", onPageHide);
    window.removeEventListener?.("pageshow", onPageShow);
    document.removeEventListener?.("visibilitychange", onVisibilityChange);
    blockMutations("Control-plane page is closing.");
    if (client) {
      try {
        await client.close();
      } catch {
        // Local state is already cleared by RuntimeClient.close().
      }
    }
  };

  return Object.freeze({
    get app() {
      return app;
    },
    get client() {
      return client;
    },
    get transport() {
      return transport;
    },
    refresh,
    reconnect: recoverSession,
    dispose,
  });
}

if (typeof document !== "undefined" && typeof window !== "undefined") {
  const root = document.querySelector?.("#app");
  if (root) {
    void startControlPlane().catch((error) => renderFatal(root, error));
  }
}

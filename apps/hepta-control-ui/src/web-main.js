import { ControlPlaneApp } from "./browser-app.js";
import { createAccessibleConfirmAction, loadBrowserBootstrap } from "./browser-host.js";
import { SameOriginHttpTransport } from "./http-transport.js";
import { LocalStoragePendingStore } from "./pending-store.js";
import {
  ERROR_CODES,
  canonicalSha256,
  fail,
  positiveInteger,
  requireDigest,
  stableId,
} from "./protocol.js";
import { RuntimeClient } from "./runtime-client.js";

const PERSISTENCE_DOMAIN_SCHEMA = "hepta.ui-control.persistence-domain.v1";
const RUNTIME_BINDING_SCHEMA = "hepta.ui-control.runtime-binding.v1";

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
    persistenceNamespace,
  });
  const runtimeBinding = await canonicalSha256({
    schema: RUNTIME_BINDING_SCHEMA,
    endpointId,
    protocolVersion,
    manifestDigest,
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
    runtimeBinding,
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
  let lifecycleGeneration = 0;
  let suspended = false;
  let disposed = false;

  const lifecycleCurrent = (generation) =>
    generation === lifecycleGeneration && !suspended && !disposed;

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

  const installRuntime = async (nextConfig, expectedGeneration = lifecycleGeneration) => {
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
    if (!lifecycleCurrent(expectedGeneration)) {
      try {
        await nextClient.close();
      } catch {
        // Stale lifecycle work never becomes current even if close acknowledgement is lost.
      }
      return false;
    }
    const nextApp = new ControlPlaneApp({
      root,
      client: nextClient,
      confirmAction,
    });

    config = nextConfig;
    transport = nextTransport;
    client = nextClient;
    app = nextApp;
    return true;
  };

  const applyCurrentSnapshot = async (expectedGeneration = lifecycleGeneration) => {
    const observedTransport = transport;
    const observedClient = client;
    const observedApp = app;
    if (!observedTransport || !observedClient || !observedApp) return null;

    const snapshot = await observedTransport.readSnapshot();
    if (
      !lifecycleCurrent(expectedGeneration) ||
      observedTransport !== transport ||
      observedClient !== client ||
      observedApp !== app
    ) {
      return null;
    }
    observedClient.applySnapshot(snapshot);
    observedApp.setMutationBlock(null);
    root.setAttribute("data-hepta-ready", "true");
    return observedClient.readView();
  };

  const stopTimer = () => {
    if (timer !== null) window.clearInterval(timer);
    timer = null;
  };

  const startTimer = () => {
    stopTimer();
    if (disposed || suspended || !config) return;
    timer = window.setInterval(() => void refresh().catch(() => {}), config.snapshotPollMs);
  };

  const recoverSession = async (reason = "Runtime session is being re-established.") => {
    if (disposed || suspended) return null;
    if (recoveryPromise) return recoveryPromise;

    stopTimer();
    const recoveryGeneration = ++lifecycleGeneration;
    blockMutations(reason);
    recoveryPromise = (async () => {
      const nextConfig = await loadConfig();
      if (!lifecycleCurrent(recoveryGeneration)) return null;

      const samePersistenceDomain =
        config !== null && nextConfig.persistenceKey === config.persistenceKey;
      const sameRuntimeBinding =
        config !== null && nextConfig.runtimeBinding === config.runtimeBinding;

      if (client && samePersistenceDomain && !sameRuntimeBinding) {
        fail(
          ERROR_CODES.INCOMPATIBLE_PROTOCOL,
          "runtime bootstrap binding changed; reload before reconciling the durable pending domain",
        );
      }

      if (client && samePersistenceDomain) {
        const recoveringClient = client;
        try {
          await recoveringClient.close();
        } catch {
          // close is best-effort here; RuntimeClient still clears local session state.
        }
        if (!lifecycleCurrent(recoveryGeneration)) return null;

        await recoveringClient.connect(connectArgs(nextConfig));
        if (!lifecycleCurrent(recoveryGeneration)) {
          try {
            await recoveringClient.close();
          } catch {
            // A suspended/disposed page must not retain the just-opened session.
          }
          return null;
        }
        config = nextConfig;
      } else {
        const previousClient = client;
        if (previousClient) {
          try {
            await previousClient.close();
          } catch {
            // The old principal/domain mirror remains isolated under its old key.
          }
        }
        if (!lifecycleCurrent(recoveryGeneration)) return null;
        const installed = await installRuntime(nextConfig, recoveryGeneration);
        if (!installed) return null;
      }

      const view = await applyCurrentSnapshot(recoveryGeneration);
      if (lifecycleCurrent(recoveryGeneration)) startTimer();
      return view;
    })().finally(() => {
      recoveryPromise = null;
    });
    return recoveryPromise;
  };

  const refreshOnce = async () => {
    const refreshGeneration = lifecycleGeneration;
    try {
      return await applyCurrentSnapshot(refreshGeneration);
    } catch (error) {
      if (!lifecycleCurrent(refreshGeneration)) return null;
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

  const initialGeneration = lifecycleGeneration;
  const installed = await installRuntime(await loadConfig(), initialGeneration);
  if (!installed) return null;
  await applyCurrentSnapshot(initialGeneration);
  startTimer();

  const onOffline = () => {
    stopTimer();
    lifecycleGeneration += 1;
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
    lifecycleGeneration += 1;
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
    lifecycleGeneration += 1;
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

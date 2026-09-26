import {
  UI_CONTROL_ERROR_CODES,
  UiControlError,
} from "./errors.js";

const RECOVERY_STORAGE_KEY = "hepta.ui-control.recovery-state.v1";

function requiredElement(document, id) {
  const element = document.getElementById(id);
  if (!element) throw new TypeError(`missing browser shell element: ${id}`);
  return element;
}

function text(document, value) {
  return document.createTextNode(String(value));
}

function formatTime(timestamp) {
  if (!timestamp) return "—";
  try {
    return new Date(timestamp).toISOString();
  } catch {
    return "—";
  }
}

export function createControlConsole({
  document = globalThis.document,
  client,
  sessionProvider,
  storage = globalThis.localStorage,
  pollIntervalMs = 2_000,
}) {
  if (!document || !client || !sessionProvider) {
    throw new TypeError("document, client, and sessionProvider are required");
  }
  if (!Number.isSafeInteger(pollIntervalMs) || pollIntervalMs < 250 || pollIntervalMs > 60_000) {
    throw new TypeError("pollIntervalMs must be a safe integer in [250, 60000]");
  }

  const elements = {
    connection: requiredElement(document, "connection-state"),
    identity: requiredElement(document, "identity-state"),
    generation: requiredElement(document, "generation-state"),
    revision: requiredElement(document, "revision-state"),
    stale: requiredElement(document, "stale-banner"),
    live: requiredElement(document, "live-status"),
    error: requiredElement(document, "error-status"),
    modules: requiredElement(document, "modules-body"),
    target: requiredElement(document, "target-id"),
    reason: requiredElement(document, "operation-reason"),
    refresh: requiredElement(document, "refresh-view"),
    start: requiredElement(document, "request-start"),
    reconcile: requiredElement(document, "request-reconcile"),
    stop: requiredElement(document, "request-stop"),
    pending: requiredElement(document, "pending-list"),
    dialog: requiredElement(document, "confirm-operation"),
    dialogTitle: requiredElement(document, "confirm-title"),
    dialogSummary: requiredElement(document, "confirm-summary"),
    confirm: requiredElement(document, "confirm-submit"),
    cancel: requiredElement(document, "confirm-cancel"),
  };

  let timer = null;
  let destroyed = false;
  let inFlight = false;
  let pendingAction = null;
  let dialogTrigger = null;

  function announce(message) {
    elements.live.textContent = message;
  }

  function showError(error) {
    const code = error instanceof UiControlError ? error.code : "UI_CONTROL_UNEXPECTED";
    elements.error.hidden = false;
    elements.error.textContent = `${code}: ${error?.message ?? String(error)}`;
    announce(elements.error.textContent);
  }

  function clearError() {
    elements.error.hidden = true;
    elements.error.textContent = "";
  }

  function persistRecovery() {
    if (!storage) return;
    const state = client.exportRecoveryState();
    if (state.operations.length === 0) {
      storage.removeItem(RECOVERY_STORAGE_KEY);
    } else {
      storage.setItem(RECOVERY_STORAGE_KEY, JSON.stringify(state));
    }
  }

  function restoreRecovery() {
    if (!storage) return;
    const value = storage.getItem(RECOVERY_STORAGE_KEY);
    if (!value) return;
    try {
      client.restoreRecoveryState(JSON.parse(value));
    } catch {
      storage.removeItem(RECOVERY_STORAGE_KEY);
    }
  }

  function renderModules(view) {
    elements.modules.replaceChildren();
    elements.target.replaceChildren();
    if (!view.snapshot || view.snapshot.modules.length === 0) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 4;
      cell.textContent = view.stale ? "No current runtime snapshot." : "No runtime modules reported.";
      row.append(cell);
      elements.modules.append(row);
      return;
    }
    for (const module of view.snapshot.modules) {
      const row = document.createElement("tr");
      for (const value of [module.id, module.status, module.revision, module.semanticDigest]) {
        const cell = document.createElement("td");
        cell.textContent = String(value);
        row.append(cell);
      }
      elements.modules.append(row);
      const option = document.createElement("option");
      option.value = module.id;
      option.textContent = module.id;
      elements.target.append(option);
    }
  }

  function renderPending(view) {
    elements.pending.replaceChildren();
    if (view.pending.length === 0) {
      const item = document.createElement("li");
      item.textContent = "No pending operations.";
      elements.pending.append(item);
      return;
    }
    for (const operation of view.pending) {
      const item = document.createElement("li");
      const label = document.createElement("span");
      label.textContent = [
        operation.operationId,
        operation.state,
        operation.auditTraceId ?? "audit pending",
        `generation ${operation.generation}`,
        `revision ${operation.displayedRevision}`,
      ].join(" · ");
      item.append(label);
      if (operation.state === "indeterminate") {
        const recover = document.createElement("button");
        recover.type = "button";
        recover.textContent = "Recover operation";
        recover.dataset.operationId = operation.operationId;
        recover.addEventListener("click", async () => {
          clearError();
          recover.disabled = true;
          try {
            const result = await client.recoverOperation(operation.operationId);
            announce(`Recovered ${result.operationId}: ${result.state}.`);
            persistRecovery();
            render();
          } catch (error) {
            showError(error);
          } finally {
            recover.disabled = false;
          }
        });
        item.append(text(document, " "), recover);
      }
      elements.pending.append(item);
    }
  }

  function render() {
    const view = client.readView();
    elements.connection.textContent = view.connected ? "Connected" : "Disconnected";
    elements.identity.textContent = view.sessionId ?? "—";
    elements.generation.textContent = view.snapshot?.generation ?? "—";
    elements.revision.textContent = view.snapshot?.revision ?? "—";
    elements.stale.hidden = !view.stale;
    elements.stale.textContent = view.stale
      ? "The displayed runtime view is stale. Control actions are disabled until refresh succeeds."
      : "";
    renderModules(view);
    renderPending(view);

    const hasTarget = elements.target.options.length > 0;
    const disabled = destroyed || inFlight || view.stale || !view.connected || !hasTarget;
    elements.start.disabled =
      disabled || !view.permissions.includes("hepta://ui.control/runtime.start");
    elements.reconcile.disabled =
      disabled || !view.permissions.includes("hepta://ui.control/runtime.request");
    elements.stop.disabled =
      disabled || !view.permissions.includes("hepta://ui.control/runtime.stop");
    elements.refresh.disabled = destroyed || inFlight || !view.connected;
  }

  function openConfirmation(action, trigger) {
    clearError();
    const view = client.readView();
    if (view.stale || !view.snapshot) {
      showError(
        new UiControlError(
          UI_CONTROL_ERROR_CODES.STALE_REVISION,
          "Refresh the runtime view before submitting an operation.",
        ),
      );
      return;
    }
    const targetId = elements.target.value;
    const reason = elements.reason.value.trim();
    if (!targetId || !reason) {
      showError(
        new UiControlError(
          UI_CONTROL_ERROR_CODES.INVALID_INPUT,
          "Choose a target and provide a reason before submitting.",
        ),
      );
      return;
    }
    pendingAction = Object.freeze({
      action,
      targetId,
      reason,
      displayedRevision: view.snapshot.revision,
      operationId: `ui:${globalThis.crypto.randomUUID()}`,
    });
    dialogTrigger = trigger;
    elements.dialogTitle.textContent = action === "request_stop"
      ? "Confirm runtime stop request"
      : action === "request_start"
        ? "Confirm runtime start request"
        : "Confirm runtime reconciliation request";
    elements.dialogSummary.textContent = [
      `Target: ${targetId}`,
      `Generation: ${view.snapshot.generation}`,
      `Revision: ${view.snapshot.revision}`,
      `Operation ID: ${pendingAction.operationId}`,
      `Reason: ${reason}`,
    ].join(". ");
    elements.dialog.showModal();
    elements.confirm.focus();
  }

  async function submitConfirmed() {
    if (!pendingAction || inFlight) return;
    const action = pendingAction;
    pendingAction = null;
    inFlight = true;
    elements.confirm.disabled = true;
    clearError();
    render();
    try {
      let result;
      if (action.action === "request_stop") {
        result = await client.requestStop(action);
      } else if (action.action === "request_start") {
        result = await client.requestStart(action);
      } else {
        result = await client.submitRequest(action);
      }
      announce(
        `Submitted ${result.operationId}. Audit trace ${result.auditTraceId ?? "pending"}.`,
      );
    } catch (error) {
      showError(error);
    } finally {
      persistRecovery();
      inFlight = false;
      elements.confirm.disabled = false;
      if (elements.dialog.open) elements.dialog.close();
      render();
      dialogTrigger?.focus();
      dialogTrigger = null;
    }
  }

  async function refresh({ propagate = false } = {}) {
    if (inFlight) return;
    inFlight = true;
    clearError();
    render();
    let failure = null;
    try {
      await client.refreshView();
      await client.recoverPending({ limit: 32 });
      persistRecovery();
      announce(`Runtime view refreshed at ${formatTime(Date.now())}.`);
    } catch (error) {
      failure = error;
      showError(error);
    } finally {
      inFlight = false;
      render();
    }
    if (failure && propagate) throw failure;
  }

  elements.refresh.addEventListener("click", refresh);
  elements.start.addEventListener("click", event =>
    openConfirmation("request_start", event.currentTarget),
  );
  elements.reconcile.addEventListener("click", event =>
    openConfirmation("request_reconcile", event.currentTarget),
  );
  elements.stop.addEventListener("click", event =>
    openConfirmation("request_stop", event.currentTarget),
  );
  elements.confirm.addEventListener("click", submitConfirmed);
  elements.cancel.addEventListener("click", () => {
    pendingAction = null;
    elements.dialog.close();
    dialogTrigger?.focus();
    dialogTrigger = null;
  });
  elements.dialog.addEventListener("cancel", event => {
    event.preventDefault();
    pendingAction = null;
    elements.dialog.close();
    dialogTrigger?.focus();
    dialogTrigger = null;
  });

  const unsubscribe = sessionProvider.subscribe(event => {
    if (event.type === "revoked" || event.type === "refresh-failed") {
      showError(
        event.error ??
          new UiControlError(
            UI_CONTROL_ERROR_CODES.SESSION_REVOKED,
            "The authenticated session was revoked.",
          ),
      );
    }
    render();
  });

  return Object.freeze({
    async start({ signal } = {}) {
      restoreRecovery();
      clearError();
      try {
        await sessionProvider.start({ signal });
        await refresh({ propagate: true });
        timer = setInterval(() => {
          refresh().catch(showError);
        }, pollIntervalMs);
        announce("ui.control console connected.");
      } catch (error) {
        showError(error);
        throw error;
      }
      render();
    },

    render,

    async destroy() {
      if (destroyed) return;
      destroyed = true;
      if (timer !== null) clearInterval(timer);
      timer = null;
      unsubscribe();
      sessionProvider.stop();
      persistRecovery();
      await client.close();
      render();
    },
  });
}

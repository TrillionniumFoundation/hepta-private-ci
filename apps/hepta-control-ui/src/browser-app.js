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

function redactIdentifier(value) {
  if (value === null || value === undefined || value === "") return "—";
  const input = String(value);
  if (input.length <= 4) return "••••";
  if (input.length <= 12) return `${input.slice(0, 4)}…${input.slice(-2)}`;
  return `${input.slice(0, 8)}…${input.slice(-6)}`;
}

function redactDigest(value) {
  if (value === null || value === undefined || value === "") return "—";
  const input = String(value);
  if (input.length <= 24) return redactIdentifier(input);
  return `${input.slice(0, 12)}…${input.slice(-8)}`;
}

function visibleError(error) {
  if (error instanceof UiControlError) {
    return `${error.code}: ${error.message}`;
  }
  return "UI_CONTROL_UNEXPECTED: An unexpected ui.control failure occurred.";
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
    session: requiredElement(document, "session-state"),
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
    completed: requiredElement(document, "completed-list"),
    dialog: requiredElement(document, "confirm-operation"),
    dialogTitle: requiredElement(document, "confirm-title"),
    dialogSummary: requiredElement(document, "confirm-summary"),
    confirm: requiredElement(document, "confirm-submit"),
    cancel: requiredElement(document, "confirm-cancel"),
  };

  let timer = null;
  let destroyed = false;
  let started = false;
  let startPromise = null;
  let lifecycleEpoch = 0;
  let inFlight = false;
  let pendingAction = null;
  let dialogTrigger = null;

  function announce(message) {
    elements.live.textContent = message;
  }

  function showError(error) {
    elements.error.hidden = false;
    elements.error.textContent = visibleError(error);
    announce(elements.error.textContent);
  }

  function appendError(error) {
    const message = visibleError(error);
    if (elements.error.hidden || elements.error.textContent.length === 0) {
      showError(error);
      return;
    }
    elements.error.textContent = `${elements.error.textContent} ${message}`;
    announce(elements.error.textContent);
  }

  function clearError() {
    elements.error.hidden = true;
    elements.error.textContent = "";
  }

  function reportStorageFailure(cause, operation) {
    appendError(
      new UiControlError(
        UI_CONTROL_ERROR_CODES.STORAGE,
        `Local recovery state could not be ${operation}; server-side operation authority is unchanged.`,
        {
          retryable: true,
          details: { operation },
          cause,
        },
      ),
    );
  }

  function persistRecovery() {
    if (!storage) return false;
    try {
      const state = client.exportRecoveryState();
      if (state.operations.length === 0) {
        storage.removeItem(RECOVERY_STORAGE_KEY);
      } else {
        storage.setItem(RECOVERY_STORAGE_KEY, JSON.stringify(state));
      }
      return true;
    } catch (error) {
      reportStorageFailure(error, "persisted");
      return false;
    }
  }

  function restoreRecovery() {
    if (!storage) return false;
    let value;
    try {
      value = storage.getItem(RECOVERY_STORAGE_KEY);
    } catch (error) {
      reportStorageFailure(error, "read");
      return false;
    }
    if (!value) return true;
    try {
      client.restoreRecoveryState(JSON.parse(value));
      return true;
    } catch (error) {
      try {
        storage.removeItem(RECOVERY_STORAGE_KEY);
      } catch {
        // The original typed storage error below is the actionable signal.
      }
      reportStorageFailure(error, "restored");
      return false;
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
      for (const value of [
        module.id,
        module.status,
        module.revision,
        redactDigest(module.semanticDigest),
      ]) {
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
        redactIdentifier(operation.operationId),
        operation.state,
        redactIdentifier(operation.auditTraceId) || "audit pending",
        `generation ${operation.generation}`,
        `revision ${operation.displayedRevision}`,
        `digest ${redactDigest(operation.semanticDigest)}`,
      ].join(" · ");
      item.append(label);
      if (operation.state === "indeterminate") {
        const recover = document.createElement("button");
        recover.type = "button";
        recover.textContent = "Recover operation";
        recover.setAttribute(
          "aria-label",
          `Recover operation ${redactIdentifier(operation.operationId)}`,
        );
        recover.disabled = destroyed || !view.connected;
        recover.addEventListener("click", async () => {
          clearError();
          recover.disabled = true;
          try {
            const result = await client.recoverOperation(operation.operationId);
            announce(`Recovered ${redactIdentifier(result.operationId)}: ${result.state}.`);
            persistRecovery();
            render();
          } catch (error) {
            showError(error);
          } finally {
            recover.disabled = destroyed || !client.readView().connected;
          }
        });
        item.append(text(document, " "), recover);
      }
      elements.pending.append(item);
    }
  }

  function renderCompleted(view) {
    elements.completed.replaceChildren();
    if (view.completed.length === 0) {
      const item = document.createElement("li");
      item.textContent = "No terminal operations observed in this session.";
      elements.completed.append(item);
      return;
    }
    for (const operation of view.completed) {
      const item = document.createElement("li");
      item.textContent = [
        redactIdentifier(operation.operationId),
        operation.terminalStatus ?? "terminal",
        operation.auditTraceId
          ? redactIdentifier(operation.auditTraceId)
          : "audit unavailable",
        `generation ${operation.generation}`,
        `revision ${operation.displayedRevision}`,
        `digest ${redactDigest(operation.semanticDigest)}`,
        operation.outcomeDigest
          ? `outcome ${redactDigest(operation.outcomeDigest)}`
          : "outcome unavailable",
      ].join(" · ");
      elements.completed.append(item);
    }
  }

  function render() {
    const view = client.readView();
    elements.connection.textContent = view.connected ? "Connected" : "Disconnected";
    elements.session.textContent = redactIdentifier(view.sessionId);
    elements.identity.textContent = view.identityId ?? "—";
    elements.generation.textContent = view.snapshot?.generation ?? "—";
    elements.revision.textContent = view.snapshot?.revision ?? "—";
    elements.stale.hidden = !view.stale;
    elements.stale.textContent = view.stale
      ? "The displayed runtime view is stale. Control actions are disabled until refresh succeeds."
      : "";
    renderModules(view);
    renderPending(view);
    renderCompleted(view);

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
      `Snapshot digest: ${redactDigest(view.snapshot.semanticDigest)}`,
      `Operation ID: ${redactIdentifier(pendingAction.operationId)}`,
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
        `Submitted ${redactIdentifier(result.operationId)}. Audit trace ${
          result.auditTraceId ? redactIdentifier(result.auditTraceId) : "pending"
        }.`,
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

  function assertLifecycleActive(epoch, phase) {
    if (destroyed || epoch !== lifecycleEpoch) {
      throw new UiControlError(
        UI_CONTROL_ERROR_CODES.ABORTED,
        `ui.control console was destroyed while ${phase}`,
        {
          retryable: true,
          details: { phase },
        },
      );
    }
  }

  async function startOnce(signal, epoch) {
    clearError();
    restoreRecovery();
    try {
      await sessionProvider.start({ signal });
      assertLifecycleActive(epoch, "establishing its session");
      await refresh({ propagate: true });
      assertLifecycleActive(epoch, "refreshing its first runtime view");
      if (timer === null) {
        timer = setInterval(() => {
          refresh().catch(showError);
        }, pollIntervalMs);
      }
      started = true;
      announce("ui.control console connected.");
      render();
    } catch (error) {
      if (!destroyed) showError(error);
      throw error;
    }
  }

  return Object.freeze({
    start({ signal } = {}) {
      if (destroyed) {
        return Promise.reject(
          new UiControlError(
            UI_CONTROL_ERROR_CODES.ABORTED,
            "ui.control console cannot restart after destroy",
            { details: { phase: "start" } },
          ),
        );
      }
      if (started) return Promise.resolve();
      if (startPromise) return startPromise;

      const epoch = lifecycleEpoch;
      const attempt = startOnce(signal, epoch);
      startPromise = attempt;
      attempt.finally(() => {
        if (startPromise === attempt) startPromise = null;
      }).catch(() => {});
      return attempt;
    },

    render,

    async destroy() {
      if (destroyed) return;
      destroyed = true;
      started = false;
      lifecycleEpoch += 1;
      if (timer !== null) clearInterval(timer);
      timer = null;
      unsubscribe();
      sessionProvider.stop();
      persistRecovery();
      try {
        await client.close();
      } finally {
        render();
      }
    },
  });
}

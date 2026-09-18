import { ERROR_CODES, fail, requireRecord, snapshotCanonical } from "./protocol.js";

const ACTIONS = Object.freeze([
  ["Retry", "request_retry"],
  ["Reconcile", "request_reconcile"],
  ["Quarantine", "request_quarantine"],
  ["Rollback", "request_rollback"],
]);

function requireRoot(root) {
  if (
    root === null ||
    typeof root !== "object" ||
    typeof root.replaceChildren !== "function" ||
    typeof root.ownerDocument?.createElement !== "function"
  ) {
    fail(ERROR_CODES.INVALID_INPUT, "root must be a DOM element with an ownerDocument");
  }
  return root;
}

function text(document, tag, value) {
  const element = document.createElement(tag);
  element.textContent = String(value);
  return element;
}

function actionKey(module, action, displayedRevision) {
  return `action:${module.moduleId}:${module.revision}:${displayedRevision}:${action}`;
}

function focusKey(module, action) {
  return `action:${module.moduleId}:${action}`;
}

export function buildControlViewModel(view) {
  requireRecord(view, "view");
  if (!Array.isArray(view.modules)) {
    fail(ERROR_CODES.INVALID_INPUT, "view.modules must be an array");
  }
  const stale = view.stale === true;
  const modules = Object.freeze(
    view.modules.map((module) =>
      Object.freeze({
        moduleId: module.moduleId,
        status: module.status,
        revision: module.revision,
        digest: module.digest,
        ready: module.ready === true,
      }),
    ),
  );
  return Object.freeze({
    stale,
    generation: view.generation,
    revision: view.revision,
    pending: view.pending ?? 0,
    indeterminate: view.indeterminate ?? 0,
    recoveryRequired: view.recoveryRequired ?? 0,
    canMutate: !stale && Number.isSafeInteger(view.revision) && view.revision > 0,
    modules,
  });
}

export class ControlPlaneApp {
  #root;
  #document;
  #client;
  #confirmAction;
  #operationIdFactory;
  #stopScopeFactory;
  #status = null;
  #view = null;
  #busy = new Set();
  #mutationBlock = null;

  constructor({
    root,
    client,
    confirmAction = async () => false,
    operationIdFactory = () => `ui.${globalThis.crypto.randomUUID()}`,
    stopScopeFactory = () => ({ scopeKind: "runtime", targetId: "runtime.agentd" }),
  }) {
    this.#root = requireRoot(root);
    this.#document = root.ownerDocument;
    requireRecord(client, "client");
    for (const method of ["readView", "submitRequest", "requestStop"]) {
      if (typeof client[method] !== "function") {
        fail(ERROR_CODES.INVALID_INPUT, `client.${method} must be a function`);
      }
    }
    if (typeof confirmAction !== "function") {
      fail(ERROR_CODES.INVALID_INPUT, "confirmAction must be a function");
    }
    if (typeof operationIdFactory !== "function") {
      fail(ERROR_CODES.INVALID_INPUT, "operationIdFactory must be a function");
    }
    if (typeof stopScopeFactory !== "function") {
      fail(ERROR_CODES.INVALID_INPUT, "stopScopeFactory must be a function");
    }
    this.#client = client;
    this.#confirmAction = confirmAction;
    this.#operationIdFactory = operationIdFactory;
    this.#stopScopeFactory = stopScopeFactory;
  }

  setMutationBlock(reason = null) {
    if (reason !== null && (typeof reason !== "string" || reason.length === 0 || reason.length > 512)) {
      fail(ERROR_CODES.INVALID_INPUT, "mutation block reason must be null or a bounded string");
    }
    this.#mutationBlock = reason;
    return this.render();
  }

  render({ restoreFocusKey = null } = {}) {
    const view = buildControlViewModel(this.#client.readView());
    this.#view = view;
    const canMutate = view.canMutate && this.#mutationBlock === null;
    const document = this.#document;
    const focusTargets = new Map();
    const main = document.createElement("main");
    main.setAttribute("aria-labelledby", "control-title");

    const title = text(document, "h1", "Hepta control plane");
    title.setAttribute("id", "control-title");
    main.append(title);

    const status = document.createElement("div");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.setAttribute("aria-atomic", "true");
    status.textContent = this.#mutationBlock !== null
      ? `${this.#mutationBlock} Mutating controls are disabled.`
      : view.stale
        ? "Runtime view is stale. Mutating controls are disabled."
        : `Runtime generation ${view.generation}, revision ${view.revision}.`;
    main.append(status);
    this.#status = status;

    const counters = text(
      document,
      "p",
      `Pending requests: ${view.pending}; indeterminate requests: ${view.indeterminate}; manual recovery required: ${view.recoveryRequired}.`,
    );
    main.append(counters);

    if (view.pending > 0 && typeof this.#client.reconcilePending === "function") {
      const reconcilePending = document.createElement("button");
      reconcilePending.setAttribute("type", "button");
      reconcilePending.setAttribute("data-focus-key", "reconcile-pending");
      reconcilePending.textContent =
        view.recoveryRequired > 0
          ? "Reconcile unresolved operations"
          : "Refresh pending operation status";
      const reconcileBusyKey = "reconcile-pending";
      reconcilePending.disabled =
        this.#mutationBlock !== null || this.#busy.has(reconcileBusyKey);
      reconcilePending.addEventListener(
        "click",
        () => void this.#requestPendingReconciliation(reconcilePending),
      );
      focusTargets.set("reconcile-pending", reconcilePending);
      main.append(reconcilePending);
    }

    const stop = document.createElement("button");
    stop.setAttribute("type", "button");
    stop.setAttribute("data-focus-key", "stop");
    stop.textContent = "Request runtime stop";
    const stopBusyKey = `stop:${view.revision}`;
    stop.disabled = !canMutate || this.#busy.has(stopBusyKey);
    stop.addEventListener("click", () => void this.#requestStop(stop));
    focusTargets.set("stop", stop);
    main.append(stop);

    const table = document.createElement("table");
    const caption = text(document, "caption", "Runtime modules");
    table.append(caption);
    const header = document.createElement("tr");
    for (const label of ["Module", "Status", "Revision", "Actions"]) {
      const cell = text(document, "th", label);
      cell.setAttribute("scope", "col");
      header.append(cell);
    }
    const head = document.createElement("thead");
    head.append(header);
    table.append(head);

    const body = document.createElement("tbody");
    for (const module of view.modules) {
      const row = document.createElement("tr");
      const moduleCell = text(document, "th", module.moduleId);
      moduleCell.setAttribute("scope", "row");
      row.append(moduleCell);
      row.append(text(document, "td", module.status));
      row.append(text(document, "td", module.revision));
      const actions = document.createElement("td");
      for (const [label, action] of ACTIONS) {
        const button = document.createElement("button");
        const key = actionKey(module, action, view.revision);
        const focus = focusKey(module, action);
        button.setAttribute("type", "button");
        button.setAttribute("data-focus-key", focus);
        button.textContent = `${label} ${module.moduleId}`;
        button.disabled = !canMutate || this.#busy.has(key);
        button.addEventListener("click", () => void this.#requestModuleAction(module, action, button));
        focusTargets.set(focus, button);
        actions.append(button);
      }
      row.append(actions);
      body.append(row);
    }
    table.append(body);
    main.append(table);
    this.#root.replaceChildren(main);

    if (restoreFocusKey !== null) {
      const target = focusTargets.get(restoreFocusKey);
      if (target?.focus) {
        target.focus();
      } else {
        status.setAttribute("tabindex", "-1");
        status.focus?.();
      }
    }
    return view;
  }

  async #requestModuleAction(module, action, button) {
    const view = this.#view;
    if (!view?.canMutate || this.#mutationBlock !== null) return;
    const busyKey = actionKey(module, action, view.revision);
    const restore = focusKey(module, action);
    if (this.#busy.has(busyKey)) {
      this.#announce("An identical request is already awaiting confirmation or acknowledgement.");
      return;
    }
    this.#busy.add(busyKey);
    if (button) button.disabled = true;
    this.#setBusyState();
    try {
      let request;
      try {
        request = Object.freeze({
          operationId: this.#operationIdFactory(),
          subjectId: module.moduleId,
          action,
          expectedRevision: module.revision,
          displayedRevision: view.revision,
        });
      } catch (error) {
        this.#announce(`Request construction failed: ${error?.message ?? "unknown error"}`, true);
        return;
      }
      await this.#executeConfirmed(
        "operation",
        request,
        () => this.#client.submitRequest(request),
        restore,
        () => {
          this.#busy.delete(busyKey);
          this.#setBusyState();
        },
      );
    } finally {
      this.#busy.delete(busyKey);
      this.#setBusyState();
      if (button && this.#view?.canMutate && this.#mutationBlock === null) button.disabled = false;
    }
  }

  async #requestPendingReconciliation(button) {
    if (
      this.#mutationBlock !== null ||
      typeof this.#client.reconcilePending !== "function" ||
      !this.#view ||
      this.#view.pending <= 0
    ) {
      return;
    }
    const busyKey = "reconcile-pending";
    if (this.#busy.has(busyKey)) {
      this.#announce("A pending-operation reconciliation batch is already running.");
      return;
    }
    this.#busy.add(busyKey);
    if (button) button.disabled = true;
    this.#setBusyState();
    try {
      const result = await this.#client.reconcilePending({ force: true });
      this.#busy.delete(busyKey);
      this.#setBusyState();
      this.render({ restoreFocusKey: "reconcile-pending" });
      this.#announce(
        `Reconciliation batch completed; pending ${result.pending}, indeterminate ${result.indeterminate}, manual recovery required ${result.recoveryRequired}.`,
        result.recoveryRequired > 0,
      );
    } catch (error) {
      this.#busy.delete(busyKey);
      this.#setBusyState();
      try {
        this.render({ restoreFocusKey: "reconcile-pending" });
      } catch {
        // Session transitions can temporarily make the current view unavailable.
      }
      this.#announce(
        `${error?.code ?? "ERROR"}: ${error?.message ?? "reconciliation failed"}`,
        true,
      );
    } finally {
      this.#busy.delete(busyKey);
      this.#setBusyState();
      if (button && this.#mutationBlock === null) button.disabled = false;
    }
  }

  async #requestStop(button) {
    const view = this.#view;
    if (!view?.canMutate || this.#mutationBlock !== null) return;
    const busyKey = `stop:${view.revision}`;
    if (this.#busy.has(busyKey)) {
      this.#announce("A runtime stop request is already awaiting confirmation or acknowledgement.");
      return;
    }
    this.#busy.add(busyKey);
    if (button) button.disabled = true;
    this.#setBusyState();
    try {
      let request;
      try {
        const rawScope = requireRecord(this.#stopScopeFactory(view), "stop scope");
        const scope = snapshotCanonical(rawScope, "stop scope");
        request = Object.freeze({
          operationId: this.#operationIdFactory(),
          displayedRevision: view.revision,
          scope,
        });
      } catch (error) {
        this.#announce(`Request construction failed: ${error?.message ?? "unknown error"}`, true);
        return;
      }
      await this.#executeConfirmed(
        "stop",
        request,
        () => this.#client.requestStop(request),
        "stop",
        () => {
          this.#busy.delete(busyKey);
          this.#setBusyState();
        },
      );
    } finally {
      this.#busy.delete(busyKey);
      this.#setBusyState();
      if (button && this.#view?.canMutate && this.#mutationBlock === null) button.disabled = false;
    }
  }

  async #executeConfirmed(kind, request, execute, restoreFocusKey, beforeRender) {
    const restore = () => {
      beforeRender?.();
      try {
        this.render({ restoreFocusKey });
      } catch {
        // A concurrent session transition may temporarily make readView unavailable.
      }
    };

    let confirmed = false;
    try {
      confirmed = (await this.#confirmAction(Object.freeze({ kind, request }))) === true;
    } catch (error) {
      restore();
      this.#announce(`Confirmation failed: ${error?.message ?? "unknown error"}`, true);
      return;
    }
    if (!confirmed) {
      restore();
      this.#announce("Request cancelled before submission.");
      return;
    }
    if (
      !this.#view?.canMutate ||
      this.#mutationBlock !== null ||
      request.displayedRevision !== this.#view.revision
    ) {
      restore();
      this.#announce(
        "Request was invalidated by a runtime/session state change before submission.",
        true,
      );
      return;
    }
    try {
      const acknowledgement = await execute();
      restore();
      this.#announce(
        `Request ${acknowledgement.operationId} is ${acknowledgement.status}.`,
        acknowledgement.status === "indeterminate" || acknowledgement.recoveryRequired === true,
      );
    } catch (error) {
      restore();
      this.#announce(`${error?.code ?? "ERROR"}: ${error?.message ?? "request failed"}`, true);
    }
  }

  #setBusyState() {
    const busy = this.#busy.size > 0;
    if (typeof this.#root.setAttribute === "function") {
      this.#root.setAttribute("aria-busy", busy ? "true" : "false");
    }
  }

  #announce(message, alert = false) {
    if (!this.#status) return;
    this.#status.setAttribute("role", alert ? "alert" : "status");
    this.#status.textContent = message;
  }
}

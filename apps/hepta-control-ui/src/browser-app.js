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

  render() {
    const view = buildControlViewModel(this.#client.readView());
    this.#view = view;
    const document = this.#document;
    const main = document.createElement("main");
    main.setAttribute("aria-labelledby", "control-title");

    const title = text(document, "h1", "Hepta control plane");
    title.setAttribute("id", "control-title");
    main.append(title);

    const status = document.createElement("div");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.textContent = view.stale
      ? "Runtime view is stale. Mutating controls are disabled."
      : `Runtime generation ${view.generation}, revision ${view.revision}.`;
    main.append(status);
    this.#status = status;

    const counters = text(
      document,
      "p",
      `Pending requests: ${view.pending}; indeterminate requests: ${view.indeterminate}.`,
    );
    main.append(counters);

    const stop = document.createElement("button");
    stop.setAttribute("type", "button");
    stop.textContent = "Request runtime stop";
    stop.disabled = !view.canMutate;
    stop.addEventListener("click", () => void this.#requestStop());
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
        button.setAttribute("type", "button");
        button.textContent = `${label} ${module.moduleId}`;
        button.disabled = !view.canMutate;
        button.addEventListener("click", () => void this.#requestModuleAction(module, action));
        actions.append(button);
      }
      row.append(actions);
      body.append(row);
    }
    table.append(body);
    main.append(table);
    this.#root.replaceChildren(main);
    return view;
  }

  async #requestModuleAction(module, action) {
    const view = this.#view;
    if (!view?.canMutate) {
      return;
    }
    const request = Object.freeze({
      operationId: this.#operationIdFactory(),
      subjectId: module.moduleId,
      action,
      expectedRevision: module.revision,
      displayedRevision: view.revision,
    });
    await this.#executeConfirmed("operation", request, () =>
      this.#client.submitRequest(request),
    );
  }

  async #requestStop() {
    const view = this.#view;
    if (!view?.canMutate) {
      return;
    }
    const rawScope = requireRecord(this.#stopScopeFactory(view), "stop scope");
    const scope = snapshotCanonical(rawScope, "stop scope");
    const request = Object.freeze({
      operationId: this.#operationIdFactory(),
      displayedRevision: view.revision,
      scope,
    });
    await this.#executeConfirmed("stop", request, () => this.#client.requestStop(request));
  }

  async #executeConfirmed(kind, request, execute) {
    let confirmed = false;
    try {
      confirmed = (await this.#confirmAction(
        Object.freeze({ kind, request }),
      )) === true;
    } catch (error) {
      this.#announce(`Confirmation failed: ${error?.message ?? "unknown error"}`, true);
      return;
    }
    if (!confirmed) {
      this.#announce("Request cancelled before submission.");
      return;
    }
    try {
      const acknowledgement = await execute();
      this.#announce(
        `Request ${acknowledgement.operationId} is ${acknowledgement.status}.`,
        acknowledgement.status === "indeterminate",
      );
      this.render();
    } catch (error) {
      this.#announce(
        `${error?.code ?? "ERROR"}: ${error?.message ?? "request failed"}`,
        true,
      );
    }
  }

  #announce(message, alert = false) {
    if (!this.#status) {
      return;
    }
    this.#status.setAttribute("role", alert ? "alert" : "status");
    this.#status.textContent = message;
  }
}

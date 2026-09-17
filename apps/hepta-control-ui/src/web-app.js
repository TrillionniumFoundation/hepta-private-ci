import { RuntimeClient } from "./runtime-client.js";

const OPERATOR_ACTIONS = Object.freeze([
  ["request_retry", "Request retry"],
  ["request_reconcile", "Request reconcile"],
  ["request_quarantine", "Request quarantine"],
  ["request_rollback", "Request rollback"],
]);

function requireRoot(root) {
  if (
    root === null ||
    typeof root !== "object" ||
    typeof root.replaceChildren !== "function" ||
    !root.ownerDocument ||
    typeof root.ownerDocument.createElement !== "function"
  ) {
    throw new TypeError("root must be a DOM element");
  }
  return root;
}

function text(document, tag, value) {
  const node = document.createElement(tag);
  node.textContent = String(value);
  return node;
}

function button(document, label, onClick, disabled) {
  const node = document.createElement("button");
  node.type = "button";
  node.textContent = label;
  node.disabled = disabled;
  if (!disabled) {
    node.addEventListener("click", onClick);
  }
  return node;
}

export class ControlPlaneWebApp {
  #root;
  #document;
  #transport;
  #endpointManifest;
  #confirmAction;
  #operationIdFactory;
  #client;
  #unsubscribe = null;
  #lastError = null;

  constructor({
    root,
    transport,
    endpointManifest,
    confirmAction = async () => false,
    operationIdFactory = () => `ui.${globalThis.crypto.randomUUID()}`,
  }) {
    this.#root = requireRoot(root);
    this.#document = root.ownerDocument;
    if (transport === null || typeof transport !== "object") {
      throw new TypeError("transport must be an object");
    }
    if (typeof transport.subscribe !== "function") {
      throw new TypeError("transport.subscribe must be a function");
    }
    if (typeof confirmAction !== "function") {
      throw new TypeError("confirmAction must be a function");
    }
    if (typeof operationIdFactory !== "function") {
      throw new TypeError("operationIdFactory must be a function");
    }
    this.#transport = transport;
    this.#endpointManifest = endpointManifest;
    this.#confirmAction = confirmAction;
    this.#operationIdFactory = operationIdFactory;
    this.#client = new RuntimeClient({ transport });
  }

  get client() {
    return this.#client;
  }

  async start() {
    this.#lastError = null;
    const session = await this.#client.connect(this.#endpointManifest);
    const unsubscribe = await this.#transport.subscribe({
      sessionId: session.sessionId,
      onSnapshot: (snapshot) => this.#consumeSnapshot(snapshot),
      onObservation: (observation) => this.#consumeObservation(observation),
      onError: (error) => this.#renderError(error),
    });
    if (typeof unsubscribe !== "function") {
      throw new TypeError(
        "transport.subscribe must resolve to an unsubscribe function",
      );
    }
    this.#unsubscribe = unsubscribe;
    this.render();
    return session;
  }

  async stop() {
    if (this.#unsubscribe) {
      const unsubscribe = this.#unsubscribe;
      this.#unsubscribe = null;
      await unsubscribe();
    }
    await this.#client.close();
    this.#renderDisconnected();
  }

  render() {
    let view;
    try {
      view = this.#client.readView();
    } catch (error) {
      this.#renderStandaloneError(this.#lastError ?? error);
      return;
    }
    const document = this.#document;
    const fragment = document.createElement("main");
    fragment.setAttribute("aria-labelledby", "control-plane-title");

    const title = text(document, "h1", "Hepta control plane");
    title.id = "control-plane-title";
    fragment.append(title);

    let alert = null;
    if (this.#lastError) {
      const message =
        this.#lastError instanceof Error
          ? this.#lastError.message
          : "Unknown control-plane error";
      alert = text(document, "p", message);
      alert.setAttribute("role", "alert");
      alert.setAttribute("tabindex", "-1");
      fragment.append(alert);
      const code =
        this.#lastError &&
        typeof this.#lastError === "object" &&
        "code" in this.#lastError
          ? this.#lastError.code
          : null;
      if (code) {
        fragment.append(text(document, "p", `Error code: ${code}`));
      }
    }

    const status = text(
      document,
      "p",
      view.stale
        ? "Runtime view is stale. Mutating controls are disabled."
        : `Runtime generation ${view.generation}, revision ${view.revision}.`,
    );
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    fragment.append(status);

    if (view.pending > 0) {
      fragment.append(
        text(
          document,
          "p",
          `${view.pending} operation${view.pending === 1 ? "" : "s"} pending; ${view.indeterminate} indeterminate.`,
        ),
      );
    }

    const table = document.createElement("table");
    table.append(text(document, "caption", "Runtime modules"));
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const label of ["Module", "Status", "Revision", "Actions"]) {
      headRow.append(text(document, "th", label));
    }
    head.append(headRow);
    table.append(head);

    const body = document.createElement("tbody");
    for (const module of view.modules) {
      const row = document.createElement("tr");
      row.append(text(document, "td", module.moduleId));
      row.append(text(document, "td", module.status));
      row.append(text(document, "td", module.revision));
      const actions = document.createElement("td");
      const disabled = view.stale === true;
      for (const [action, label] of OPERATOR_ACTIONS) {
        actions.append(
          button(
            document,
            `${label} for ${module.moduleId}`,
            () => this.#requestOperation(module.moduleId, action, view.revision),
            disabled,
          ),
        );
      }
      actions.append(
        button(
          document,
          `Request stop for ${module.moduleId}`,
          () => this.#requestStop(module.moduleId, view.revision),
          disabled,
        ),
      );
      row.append(actions);
      body.append(row);
    }
    table.append(body);
    fragment.append(table);
    this.#root.replaceChildren(fragment);
    if (alert && typeof alert.focus === "function") {
      alert.focus();
    }
  }

  async #requestOperation(subjectId, action, displayedRevision) {
    try {
      const confirmed = await this.#confirmAction({
        requestKind: "operation",
        subjectId,
        action,
        displayedRevision,
      });
      if (confirmed !== true) {
        return;
      }
      await this.#client.submitRequest({
        displayedRevision,
        intent: {
          operationId: this.#operationIdFactory(),
          subjectId,
          action,
          expectedRevision: displayedRevision,
        },
      });
      this.#lastError = null;
      this.render();
    } catch (error) {
      this.#renderError(error);
    }
  }

  async #requestStop(subjectId, displayedRevision) {
    try {
      const confirmed = await this.#confirmAction({
        requestKind: "stop",
        subjectId,
        action: "request_stop",
        displayedRevision,
      });
      if (confirmed !== true) {
        return;
      }
      await this.#client.requestStop({
        operationId: this.#operationIdFactory(),
        scope: { subjectId },
        displayedRevision,
      });
      this.#lastError = null;
      this.render();
    } catch (error) {
      this.#renderError(error);
    }
  }

  #consumeSnapshot(snapshot) {
    try {
      this.#client.applySnapshot(snapshot);
      this.#lastError = null;
      this.render();
    } catch (error) {
      this.#renderError(error);
    }
  }

  #consumeObservation(observation) {
    try {
      this.#client.reconcile(observation);
      this.#lastError = null;
      this.render();
    } catch (error) {
      this.#renderError(error);
    }
  }

  #renderError(error) {
    this.#lastError = error;
    this.render();
  }

  #renderStandaloneError(error) {
    const message =
      error instanceof Error ? error.message : "Unknown control-plane error";
    const main = this.#document.createElement("main");
    main.append(text(this.#document, "h1", "Hepta control plane"));
    const alert = text(this.#document, "p", message);
    alert.setAttribute("role", "alert");
    alert.setAttribute("tabindex", "-1");
    main.append(alert);
    const code =
      error && typeof error === "object" && "code" in error ? error.code : null;
    if (code) {
      main.append(text(this.#document, "p", `Error code: ${code}`));
    }
    this.#root.replaceChildren(main);
    if (typeof alert.focus === "function") {
      alert.focus();
    }
  }

  #renderDisconnected() {
    const main = this.#document.createElement("main");
    main.append(text(this.#document, "h1", "Hepta control plane"));
    const status = text(this.#document, "p", "Disconnected.");
    status.setAttribute("role", "status");
    main.append(status);
    this.#root.replaceChildren(main);
  }
}

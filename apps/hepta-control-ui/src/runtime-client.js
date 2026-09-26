import {
  assertCanonicalText,
  assertSafeInteger,
  assertSha256,
  assertStableIdentifier,
  constantTimeEqual,
} from "./canonical.js";
import {
  buildOperationIntent,
  digestOperationIntent,
} from "./control.js";
import {
  UI_CONTROL_ERROR_CODES,
  uiControlError,
} from "./errors.js";
import { OperationLedger } from "./operation-ledger.js";
import {
  ACTIVE_STATUSES,
  TERMINAL_STATUSES,
  UI_CONTROL_PERMISSIONS,
  UI_CONTROL_PROTOCOL_VERSION,
  assertPlainObject,
  invalid,
  normalizeSession,
  publicOperation,
} from "./runtime-contract.js";
import {
  normalizeSnapshot,
  validateSnapshotTransition,
} from "./snapshot.js";

export { UI_CONTROL_PERMISSIONS, UI_CONTROL_PROTOCOL_VERSION } from "./runtime-contract.js";

export class RuntimeClient {
  #transport;
  #clock;
  #protocolVersion;
  #session = null;
  #snapshot = null;
  #ledger;

  constructor({
    transport,
    maxPending = 1024,
    clock = () => Date.now(),
    protocolVersion = UI_CONTROL_PROTOCOL_VERSION,
  }) {
    assertPlainObject(transport, "transport");
    for (const method of ["connect", "readSnapshot", "request", "lookup", "close"]) {
      if (typeof transport[method] !== "function") {
        throw invalid(`transport.${method} must be a function`);
      }
    }
    this.#transport = transport;
    this.#clock = clock;
    this.#protocolVersion = assertCanonicalText(protocolVersion, "protocolVersion", {
      maxBytes: 128,
    });
    this.#ledger = new OperationLedger({ maxPending, clock });
  }

  get connected() {
    return this.#session !== null;
  }

  async connect(endpointManifest, { signal } = {}) {
    const rawSession = await this.#transport.connect(endpointManifest, { signal });
    this.#session = normalizeSession(rawSession, this.#protocolVersion, this.#clock());
    this.#snapshot = null;
    return this.readView();
  }

  async refreshSession({ signal } = {}) {
    this.#assertConnected();
    if (typeof this.#transport.refresh !== "function") {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.TRANSPORT,
        "transport does not implement session refresh",
      );
    }
    const rawSession = await this.#transport.refresh(this.#session, { signal });
    const refreshed = normalizeSession(rawSession, this.#protocolVersion, this.#clock());
    if (refreshed.sessionId !== this.#session.sessionId) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.SESSION_REVOKED,
        "session refresh changed the session identity",
      );
    }
    if (refreshed.connectionGeneration < this.#session.connectionGeneration) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.STALE_GENERATION,
        "session refresh regressed connection generation",
      );
    }
    const generationChanged =
      refreshed.connectionGeneration !== this.#session.connectionGeneration;
    this.#session = refreshed;
    if (generationChanged) this.#snapshot = null;
    return this.readView();
  }

  async revokeSession({ signal } = {}) {
    if (!this.#session) return;
    const session = this.#session;
    if (typeof this.#transport.revoke === "function") {
      await this.#transport.revoke(session, { signal });
    }
    this.#session = null;
    this.#snapshot = null;
  }

  async refreshView({ signal } = {}) {
    this.#assertPermission(UI_CONTROL_PERMISSIONS.READ);
    const snapshot = await this.#transport.readSnapshot(
      {
        sessionId: this.#session.sessionId,
        connectionGeneration: this.#session.connectionGeneration,
      },
      { signal },
    );
    await this.applySnapshot(snapshot);
    return this.readView();
  }

  async applySnapshot(snapshot) {
    this.#assertConnected();
    const normalized = await normalizeSnapshot(snapshot, this.#session);
    this.#snapshot = validateSnapshotTransition(this.#snapshot, normalized);
    return this.readView();
  }

  readView() {
    const pending = this.#ledger.views();
    return Object.freeze({
      connected: this.#session !== null,
      authenticated: this.#session?.authenticated === true,
      sessionId: this.#session?.sessionId ?? null,
      connectionGeneration: this.#session?.connectionGeneration ?? null,
      permissionRevision: this.#session?.permissionRevision ?? null,
      permissions: this.#session?.permissions ?? Object.freeze([]),
      expiresAt: this.#session?.expiresAt ?? null,
      stale: this.#snapshot === null,
      snapshot: this.#snapshot,
      pending,
      pendingCount: pending.length,
      indeterminateCount: pending.filter(entry => entry.state === "indeterminate").length,
    });
  }

  async submitRequest(input) {
    return this.#submit("runtime/request", UI_CONTROL_PERMISSIONS.REQUEST, input);
  }

  async requestStart(input) {
    return this.#submit("runtime/start", UI_CONTROL_PERMISSIONS.START, {
      ...input,
      action: "request_start",
    });
  }

  async requestStop(input) {
    return this.#submit("runtime/stop", UI_CONTROL_PERMISSIONS.STOP, {
      ...input,
      action: "request_stop",
    });
  }

  async #submit(method, permission, input) {
    this.#assertPermission(permission);
    if (!this.#snapshot) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.STALE_REVISION,
        "cannot submit a control request before a current snapshot is observed",
        { retryable: true },
      );
    }
    assertPlainObject(input, "operation input");
    const operationId = assertStableIdentifier(input.operationId, "operationId");
    const displayedRevision = assertSafeInteger(
      input.displayedRevision,
      "displayedRevision",
      { min: 1 },
    );
    if (displayedRevision !== this.#snapshot.revision) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.STALE_REVISION,
        "displayed revision does not match the current snapshot",
        {
          retryable: true,
          details: {
            displayedRevision,
            currentRevision: this.#snapshot.revision,
          },
        },
      );
    }

    const action = assertCanonicalText(input.action, "action", { maxBytes: 64 });
    const targetId = assertStableIdentifier(input.targetId, "targetId");
    const reason = assertCanonicalText(input.reason, "reason", { maxBytes: 1024 });
    const intent = buildOperationIntent({
      action,
      targetId,
      generation: this.#snapshot.generation,
      displayedRevision,
      reason,
    });
    const computedSemanticDigest = await digestOperationIntent(intent);
    const semanticDigest = input.semanticDigest === undefined
      ? computedSemanticDigest
      : assertSha256(input.semanticDigest, "semanticDigest");
    if (!constantTimeEqual(semanticDigest, computedSemanticDigest)) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.OPERATION_CONFLICT,
        "semantic digest does not bind the displayed operation intent",
        { details: { operationId } },
      );
    }

    const request = Object.freeze({
      protocolVersion: this.#protocolVersion,
      method,
      operationId,
      semanticDigest,
      action,
      targetId,
      reason,
      sessionId: this.#session.sessionId,
      connectionGeneration: this.#session.connectionGeneration,
      generation: this.#snapshot.generation,
      displayedRevision,
      snapshotDigest: this.#snapshot.semanticDigest,
    });
    return this.#ledger.submit(request, input.signal, (entry, signal) =>
      this.#transport.request(
        entry.method,
        Object.freeze({
          protocolVersion: entry.protocolVersion,
          operationId: entry.operationId,
          semanticDigest: entry.semanticDigest,
          action: entry.action,
          targetId: entry.targetId,
          reason: entry.reason,
          sessionId: entry.sessionId,
          connectionGeneration: entry.connectionGeneration,
          generation: entry.generation,
          displayedRevision: entry.displayedRevision,
          snapshotDigest: entry.snapshotDigest,
        }),
        { signal },
      ),
    );
  }

  async recoverOperation(operationId, { signal } = {}) {
    this.#assertConnected();
    const id = assertStableIdentifier(operationId, "operationId");
    const completed = this.#ledger.findCompleted(id);
    if (completed) return publicOperation(completed);
    const entry = this.#ledger.find(id);
    if (!entry) {
      throw invalid("operation is not present in the local recovery ledger", {
        operationId: id,
      });
    }
    const observation = await this.#transport.lookup(
      Object.freeze({
        sessionId: this.#session.sessionId,
        connectionGeneration: this.#session.connectionGeneration,
        operationId: entry.operationId,
        semanticDigest: entry.semanticDigest,
      }),
      { signal },
    );
    assertPlainObject(observation, "operation observation");
    if (observation.found !== true) return this.#ledger.markMissing(entry);

    const observedId = assertStableIdentifier(
      observation.operationId,
      "operation observation.operationId",
    );
    const observedDigest = assertSha256(
      observation.semanticDigest,
      "operation observation.semanticDigest",
    );
    if (observedId !== entry.operationId || !constantTimeEqual(observedDigest, entry.semanticDigest)) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.ACK_MISMATCH,
        "operation lookup returned a mismatched identity",
        { details: { operationId: entry.operationId } },
      );
    }
    const status = assertCanonicalText(observation.status, "operation observation.status", {
      maxBytes: 32,
    });
    const auditTraceId = observation.auditTraceId === undefined
      ? entry.auditTraceId
      : assertStableIdentifier(observation.auditTraceId, "operation observation.auditTraceId");
    if (TERMINAL_STATUSES.has(status)) {
      return this.reconcile({
        operationId: entry.operationId,
        semanticDigest: entry.semanticDigest,
        status,
        terminalObserved: true,
        auditTraceId,
        outcomeDigest: observation.outcomeDigest,
      });
    }
    if (!ACTIVE_STATUSES.has(status)) {
      throw invalid("operation lookup returned an unknown status", { status });
    }
    return this.#ledger.markActive(entry, status, auditTraceId);
  }

  async recoverPending({ signal, limit = 32 } = {}) {
    const boundedLimit = assertSafeInteger(limit, "limit", { min: 1, max: 128 });
    const results = [];
    for (const operation of this.#ledger.views().slice(0, boundedLimit)) {
      results.push(await this.recoverOperation(operation.operationId, { signal }));
    }
    return Object.freeze(results);
  }

  reconcile(observation) {
    return this.#ledger.reconcile(observation);
  }

  exportRecoveryState() {
    return this.#ledger.exportState();
  }

  restoreRecoveryState(state) {
    this.#ledger.restoreState(state);
    return this.readView();
  }

  async close({ signal } = {}) {
    if (this.#session) {
      await this.#transport.close(this.#session, { signal });
    }
    this.#session = null;
    this.#snapshot = null;
    return this.exportRecoveryState();
  }

  #assertConnected() {
    if (!this.#session) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.NOT_CONNECTED,
        "ui.control client is not connected",
        { retryable: true },
      );
    }
    if (this.#session.expiresAt <= this.#clock()) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.SESSION_EXPIRED,
        "ui.control session has expired",
        { retryable: true, details: { expiresAt: this.#session.expiresAt } },
      );
    }
    if (this.#session.revoked) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.SESSION_REVOKED,
        "ui.control session is revoked",
      );
    }
  }

  #assertPermission(permission) {
    this.#assertConnected();
    if (!this.#session.permissions.includes(permission)) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.PERMISSION_DENIED,
        "authenticated session does not grant the requested ui.control permission",
        { details: { permission } },
      );
    }
  }
}

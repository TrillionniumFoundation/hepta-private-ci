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
  isUiControlError,
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

const SESSION_INVALIDATING_ERROR_CODES = new Set([
  UI_CONTROL_ERROR_CODES.SESSION_EXPIRED,
  UI_CONTROL_ERROR_CODES.SESSION_REVOKED,
  UI_CONTROL_ERROR_CODES.SESSION_IDENTITY_CHANGED,
  UI_CONTROL_ERROR_CODES.STALE_PERMISSION_REVISION,
  UI_CONTROL_ERROR_CODES.PROTOCOL_MISMATCH,
]);

function sameStringArray(left, right) {
  return (
    left.length === right.length &&
    left.every((value, index) => value === right[index])
  );
}

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
    if (
      transport === null ||
      (typeof transport !== "object" && typeof transport !== "function")
    ) {
      throw invalid("transport must be an object implementing the ui.control transport interface");
    }
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
    this.#session = null;
    this.#snapshot = null;
    const rawSession = await this.#transport.connect(endpointManifest, { signal });
    const connected = normalizeSession(rawSession, this.#protocolVersion, this.#clock());
    this.#session = connected;
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
    const previous = this.#session;
    let rawSession;
    try {
      rawSession = await this.#transport.refresh(previous, { signal });
    } catch (error) {
      this.#invalidateSessionForError(error, previous);
      throw error;
    }

    let refreshed;
    try {
      refreshed = normalizeSession(rawSession, this.#protocolVersion, this.#clock());
      if (this.#session !== previous) {
        throw uiControlError(
          UI_CONTROL_ERROR_CODES.STALE_GENERATION,
          "authenticated session changed while refresh was in flight",
          {
            retryable: true,
            details: {
              previousSessionId: previous.sessionId,
              currentSessionId: this.#session?.sessionId ?? null,
            },
          },
        );
      }
      if (refreshed.sessionId !== previous.sessionId) {
        throw uiControlError(
          UI_CONTROL_ERROR_CODES.SESSION_REVOKED,
          "session refresh changed the session identity",
        );
      }
      if (refreshed.identityId !== previous.identityId) {
        throw uiControlError(
          UI_CONTROL_ERROR_CODES.SESSION_IDENTITY_CHANGED,
          "session refresh changed the authenticated operator identity",
          {
            details: {
              sessionId: previous.sessionId,
              previousIdentityId: previous.identityId,
              refreshedIdentityId: refreshed.identityId,
            },
          },
        );
      }
      if (refreshed.connectionGeneration < previous.connectionGeneration) {
        throw uiControlError(
          UI_CONTROL_ERROR_CODES.STALE_GENERATION,
          "session refresh regressed connection generation",
        );
      }
      if (refreshed.permissionRevision < previous.permissionRevision) {
        throw uiControlError(
          UI_CONTROL_ERROR_CODES.STALE_PERMISSION_REVISION,
          "session refresh regressed permission revision",
          {
            details: {
              previousPermissionRevision: previous.permissionRevision,
              refreshedPermissionRevision: refreshed.permissionRevision,
            },
          },
        );
      }
      if (
        refreshed.permissionRevision === previous.permissionRevision &&
        !sameStringArray(refreshed.permissions, previous.permissions)
      ) {
        throw uiControlError(
          UI_CONTROL_ERROR_CODES.STALE_PERMISSION_REVISION,
          "session permissions changed without a permission revision change",
          {
            details: {
              permissionRevision: previous.permissionRevision,
            },
          },
        );
      }
    } catch (error) {
      if (this.#session === previous) this.#invalidateSession(previous);
      throw error;
    }

    const generationChanged =
      refreshed.connectionGeneration !== previous.connectionGeneration;
    this.#session = refreshed;
    if (generationChanged) this.#snapshot = null;
    return this.readView();
  }

  async revokeSession({ signal } = {}) {
    if (!this.#session) return;
    const session = this.#session;
    this.#invalidateSession(session);
    if (typeof this.#transport.revoke === "function") {
      await this.#transport.revoke(session, { signal });
    }
  }

  async refreshView({ signal } = {}) {
    this.#assertPermission(UI_CONTROL_PERMISSIONS.READ);
    const session = this.#session;
    let snapshot;
    try {
      snapshot = await this.#transport.readSnapshot(
        {
          sessionId: session.sessionId,
          connectionGeneration: session.connectionGeneration,
        },
        { signal },
      );
    } catch (error) {
      this.#invalidateSessionForError(error, session);
      throw error;
    }
    if (this.#session !== session) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.STALE_GENERATION,
        "authenticated session changed while reading the runtime snapshot",
        { retryable: true },
      );
    }
    await this.#applySnapshotForSession(snapshot, session);
    return this.readView();
  }

  async applySnapshot(snapshot) {
    this.#assertConnected();
    return this.#applySnapshotForSession(snapshot, this.#session);
  }

  async #applySnapshotForSession(snapshot, session) {
    try {
      const normalized = await normalizeSnapshot(snapshot, session);
      if (this.#session !== session) {
        throw uiControlError(
          UI_CONTROL_ERROR_CODES.STALE_GENERATION,
          "authenticated session changed while normalizing the runtime snapshot",
          { retryable: true },
        );
      }
      this.#snapshot = validateSnapshotTransition(this.#snapshot, normalized);
      return this.readView();
    } catch (error) {
      if (
        this.#session === session &&
        isUiControlError(error) &&
        [
          UI_CONTROL_ERROR_CODES.INVALID_INPUT,
          UI_CONTROL_ERROR_CODES.SNAPSHOT_DRIFT,
        ].includes(error.code)
      ) {
        this.#snapshot = null;
      }
      throw error;
    }
  }

  readView() {
    const pending = this.#ledger.views();
    const completed = this.#ledger.completedViews();
    return Object.freeze({
      connected: this.#session !== null,
      authenticated: this.#session?.authenticated === true,
      sessionId: this.#session?.sessionId ?? null,
      identityId: this.#session?.identityId ?? null,
      connectionGeneration: this.#session?.connectionGeneration ?? null,
      permissionRevision: this.#session?.permissionRevision ?? null,
      permissions: this.#session?.permissions ?? Object.freeze([]),
      expiresAt: this.#session?.expiresAt ?? null,
      stale: this.#snapshot === null,
      snapshot: this.#snapshot,
      pending,
      pendingCount: pending.length,
      indeterminateCount: pending.filter(entry => entry.state === "indeterminate").length,
      completed,
      completedCount: completed.length,
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
    const session = this.#session;
    const snapshot = this.#snapshot;
    if (!snapshot) {
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
    if (displayedRevision !== snapshot.revision) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.STALE_REVISION,
        "displayed revision does not match the current snapshot",
        {
          retryable: true,
          details: {
            displayedRevision,
            currentRevision: snapshot.revision,
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
      generation: snapshot.generation,
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

    if (this.#session !== session) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.STALE_GENERATION,
        "authenticated session changed while preparing the control request",
        {
          retryable: true,
          details: {
            operationId,
            observedConnectionGeneration: session.connectionGeneration,
            currentConnectionGeneration: this.#session?.connectionGeneration ?? null,
          },
        },
      );
    }
    this.#assertPermission(permission);
    const currentSnapshot = this.#snapshot;
    if (
      !currentSnapshot ||
      currentSnapshot.generation !== snapshot.generation ||
      currentSnapshot.revision !== snapshot.revision ||
      !constantTimeEqual(currentSnapshot.semanticDigest, snapshot.semanticDigest)
    ) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.STALE_REVISION,
        "runtime snapshot changed while preparing the control request",
        {
          retryable: true,
          details: {
            operationId,
            observedGeneration: snapshot.generation,
            observedRevision: snapshot.revision,
            currentGeneration: currentSnapshot?.generation ?? null,
            currentRevision: currentSnapshot?.revision ?? null,
          },
        },
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
      sessionId: session.sessionId,
      connectionGeneration: session.connectionGeneration,
      generation: snapshot.generation,
      displayedRevision,
      snapshotDigest: snapshot.semanticDigest,
    });
    try {
      return await this.#ledger.submit(request, input.signal, (entry, signal) =>
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
    } catch (error) {
      this.#invalidateSessionForError(error, session);
      throw error;
    }
  }

  async recoverOperation(operationId, { signal } = {}) {
    this.#assertConnected();
    const session = this.#session;
    const id = assertStableIdentifier(operationId, "operationId");
    const completed = this.#ledger.findCompleted(id);
    if (completed) return publicOperation(completed);
    const entry = this.#ledger.find(id);
    if (!entry) {
      throw invalid("operation is not present in the local recovery ledger", {
        operationId: id,
      });
    }
    let observation;
    try {
      observation = await this.#transport.lookup(
        Object.freeze({
          sessionId: session.sessionId,
          connectionGeneration: session.connectionGeneration,
          operationId: entry.operationId,
          semanticDigest: entry.semanticDigest,
        }),
        { signal },
      );
    } catch (error) {
      this.#invalidateSessionForError(error, session);
      throw error;
    }
    if (this.#session !== session) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.STALE_GENERATION,
        "authenticated session changed while recovering an operation",
        { retryable: true, details: { operationId: id } },
      );
    }
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
    const session = this.#session;
    const recoveryState = this.exportRecoveryState();
    this.#invalidateSession(session);
    if (session) {
      await this.#transport.close(session, { signal });
    }
    return recoveryState;
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
      const expired = this.#session;
      this.#invalidateSession(expired);
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.SESSION_EXPIRED,
        "ui.control session has expired",
        { retryable: true, details: { expiresAt: expired.expiresAt } },
      );
    }
    if (this.#session.revoked) {
      const revoked = this.#session;
      this.#invalidateSession(revoked);
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

  #invalidateSession(expectedSession) {
    if (this.#session === expectedSession) {
      this.#session = null;
      this.#snapshot = null;
    }
  }

  #invalidateSessionForError(error, expectedSession) {
    if (
      isUiControlError(error) &&
      (SESSION_INVALIDATING_ERROR_CODES.has(error.code) ||
        (error.code === UI_CONTROL_ERROR_CODES.PERMISSION_DENIED &&
          error.details.status === 403))
    ) {
      this.#invalidateSession(expectedSession);
    }
  }
}

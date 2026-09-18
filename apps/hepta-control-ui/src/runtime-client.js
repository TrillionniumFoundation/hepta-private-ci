import { buildOperationProposal, projectRuntime } from "./control.js";
import {
  ERROR_CODES,
  MAX_REQUEST_BYTES,
  UiControlError,
  MAX_VIEW_BYTES,
  canonicalSha256,
  fail,
  freezeResult,
  nonNegativeInteger,
  positiveInteger,
  readOwnDataFields,
  requireDigest,
  requireRecord,
  snapshotCanonical,
  stableId,
  utf8Bytes,
} from "./protocol.js";
import { normalizePendingRecord } from "./pending-store.js";

const STATUSES = new Set([
  "pending",
  "indeterminate",
  "succeeded",
  "failed",
  "cancelled",
  "rejected",
]);
const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled", "rejected"]);
const PERSISTABLE_STATUSES = new Set(["pending", "indeterminate"]);
const MAX_PENDING = 1024;
const MAX_MODULES = 4096;
const REQUEST_SEMANTICS_SCHEMA = "hepta.ui-control.request-semantics.v1";
const TRANSPORT_REQUEST_SCHEMA = "hepta.ui-control.transport-request.v1";
const RECONCILE_BASE_DELAY_MS = 1_000;
const RECONCILE_MAX_DELAY_MS = 60_000;
const RECONCILE_BATCH_SIZE = 8;
const RECONCILE_AUTO_ATTEMPTS = 64;
const RECONCILE_RECOVERY_AGE_MS = 24 * 60 * 60 * 1_000;
const RECONCILE_CLOCK_FUTURE_SKEW_MS = 5 * 60 * 1_000;

function cloneAcknowledgement(entry, status, extra = {}) {
  const acknowledgement = freezeResult({
    kind: "OperationAcknowledgementV1",
    method: entry.method,
    operationId: entry.operationId,
    semanticDigest: entry.semanticDigest,
    status,
    accepted: extra.accepted ?? entry.accepted ?? null,
    originSessionId: entry.originSessionId,
    originConnectionGeneration: entry.originConnectionGeneration,
    runtimeGeneration: entry.runtimeGeneration,
    displayedRevision: entry.displayedRevision,
    recoveryRequired: entry.recoveryRequired === true,
    errorCode: extra.errorCode ?? null,
  });
  entry.acknowledgement = acknowledgement;
  entry.status = status;
  if (extra.accepted !== undefined) {
    entry.accepted = extra.accepted;
  }
  return acknowledgement;
}

function sessionIdentity(session) {
  return Object.freeze({
    sessionId: session.sessionId,
    connectionGeneration: session.connectionGeneration,
  });
}

function normalizeDisplayedView(value) {
  const fields = readOwnDataFields(
    value,
    "displayedView",
    ["sessionId", "connectionGeneration", "generation", "revision", "digest"],
  );
  return Object.freeze({
    sessionId: stableId(fields.sessionId, "displayedView.sessionId"),
    connectionGeneration: positiveInteger(
      fields.connectionGeneration,
      "displayedView.connectionGeneration",
    ),
    generation: positiveInteger(fields.generation, "displayedView.generation"),
    revision: positiveInteger(fields.revision, "displayedView.revision"),
    digest: requireDigest(fields.digest, "displayedView.digest"),
  });
}

export class RuntimeClient {
  #transport;
  #pendingStore;
  #clock;
  #setTimer;
  #clearTimer;
  #timer = null;
  #timerDueAt = null;
  #connectAttempt = 0;
  #closing = false;
  #closePromise = null;
  #activeIo = 0;
  #drainWaiters = [];
  #session = null;
  #snapshot = null;
  #previousSnapshot = null;
  #pending = new Map();

  constructor({
    transport,
    pendingStore = null,
    clock = () => Date.now(),
    setTimer = globalThis.setTimeout?.bind(globalThis),
    clearTimer = globalThis.clearTimeout?.bind(globalThis),
  }) {
    requireRecord(transport, "transport");
    for (const method of ["connect", "request", "reconcile", "close"]) {
      if (typeof transport[method] !== "function") {
        fail(ERROR_CODES.INVALID_INPUT, `transport.${method} must be a function`);
      }
    }
    if (pendingStore !== null) {
      if (
        typeof pendingStore !== "object" ||
        typeof pendingStore.load !== "function" ||
        typeof pendingStore.save !== "function"
      ) {
        fail(ERROR_CODES.INVALID_INPUT, "pendingStore must provide load/save");
      }
    }
    if (typeof clock !== "function") {
      fail(ERROR_CODES.INVALID_INPUT, "clock must be a function");
    }
    if (setTimer !== undefined && typeof setTimer !== "function") {
      fail(ERROR_CODES.INVALID_INPUT, "setTimer must be a function when provided");
    }
    if (clearTimer !== undefined && typeof clearTimer !== "function") {
      fail(ERROR_CODES.INVALID_INPUT, "clearTimer must be a function when provided");
    }
    this.#transport = transport;
    this.#pendingStore = pendingStore;
    this.#clock = clock;
    this.#setTimer = setTimer;
    this.#clearTimer = clearTimer;
    this.#restorePending();
  }

  async connect(endpointManifest) {
    if (this.#closing) {
      fail(ERROR_CODES.NOT_CONNECTED, "runtime client is closing");
    }
    const manifest = readOwnDataFields(
      endpointManifest,
      "endpointManifest",
      ["endpointId", "protocolVersion", "manifestDigest"],
    );
    const endpointId = stableId(manifest.endpointId, "endpointId");
    const protocolVersion = positiveInteger(manifest.protocolVersion, "protocolVersion");
    const manifestDigest = requireDigest(manifest.manifestDigest, "manifestDigest");
    const attempt = ++this.#connectAttempt;

    let observed;
    try {
      observed = requireRecord(
        snapshotCanonical(
          await this.#transport.connect(
            Object.freeze({ endpointId, protocolVersion, manifestDigest }),
          ),
          "connection observation",
          { maxBytes: 4096 },
        ),
        "connection observation",
      );
    } catch (error) {
      if (error instanceof UiControlError) throw error;
      fail(ERROR_CODES.BACKEND_UNAVAILABLE, "runtime backend is unavailable");
    }
    if (attempt !== this.#connectAttempt) {
      fail(ERROR_CODES.PROTOCOL_VIOLATION, "superseded runtime connection cannot become current");
    }
    if (observed.authenticated !== true) {
      fail(ERROR_CODES.UNAUTHENTICATED, "runtime connection is not authenticated");
    }
    if (observed.protocolVersion !== protocolVersion) {
      fail(ERROR_CODES.INCOMPATIBLE_PROTOCOL, "runtime protocol version mismatch");
    }

    this.#cancelReconciliationTimer();
    this.#session = {
      endpointId,
      protocolVersion,
      manifestDigest,
      sessionId: stableId(observed.sessionId, "sessionId"),
      connectionGeneration: positiveInteger(
        observed.connectionGeneration,
        "connectionGeneration",
      ),
    };
    this.#snapshot = null;
    this.#previousSnapshot = null;
    this.#markPendingIndeterminate();
    this.#persistBestEffort();
    await this.#resumePending({ ignoreBackoff: true, includeRecoveryRequired: false });
    this.#scheduleReconciliation();

    return freezeResult({
      kind: "RuntimeSessionV1",
      ...this.#session,
      pendingReconciliation: this.#pending.size,
      recoveryRequired: this.#recoveryRequiredCount(),
    });
  }

  applySnapshot(snapshot) {
    this.#requireSession();
    const snapshotFields = readOwnDataFields(
      snapshot,
      "snapshot",
      ["sessionId", "connectionGeneration", "generation", "revision", "digest", "modules"],
    );
    const generation = positiveInteger(snapshotFields.generation, "generation");
    const snapshotRevision = positiveInteger(snapshotFields.revision, "revision");
    const snapshotDigest = requireDigest(snapshotFields.digest, "digest");
    if (snapshotFields.sessionId !== this.#session.sessionId) {
      fail(ERROR_CODES.PROTOCOL_VIOLATION, "snapshot session identity mismatch");
    }
    if (snapshotFields.connectionGeneration !== this.#session.connectionGeneration) {
      fail(ERROR_CODES.PROTOCOL_VIOLATION, "snapshot connection generation mismatch");
    }
    const modulesInput = snapshotFields.modules;
    if (!Array.isArray(modulesInput) || modulesInput.length > MAX_MODULES) {
      fail(ERROR_CODES.INVALID_INPUT, "snapshot.modules must be a bounded array");
    }
    if (this.#snapshot) {
      if (generation < this.#snapshot.generation) {
        fail(ERROR_CODES.STALE_SNAPSHOT, "snapshot generation regressed");
      }
      if (generation === this.#snapshot.generation && snapshotRevision <= this.#snapshot.revision) {
        fail(ERROR_CODES.STALE_SNAPSHOT, "snapshot revision did not advance");
      }
    }

    const moduleDescriptors = Object.getOwnPropertyDescriptors(modulesInput);
    const expectedModuleKeys = new Set(
      [...Array(modulesInput.length).keys()].map(String).concat("length"),
    );
    for (const key of Reflect.ownKeys(moduleDescriptors)) {
      if (typeof key !== "string" || !expectedModuleKeys.has(key)) {
        fail(ERROR_CODES.INVALID_INPUT, "snapshot.modules must contain only dense indexed data");
      }
    }

    const moduleIds = new Set();
    const modules = [];
    for (let index = 0; index < modulesInput.length; index += 1) {
      const descriptor = moduleDescriptors[String(index)];
      if (!descriptor || !Object.hasOwn(descriptor, "value") || descriptor.enumerable !== true) {
        fail(ERROR_CODES.INVALID_INPUT, "snapshot.modules must contain only dense indexed data");
      }
      const projection = projectRuntime(descriptor.value);
      if (moduleIds.has(projection.moduleId)) {
        fail(ERROR_CODES.PROTOCOL_VIOLATION, "snapshot contains duplicate module identity");
      }
      moduleIds.add(projection.moduleId);
      modules.push(projection);
    }
    Object.freeze(modules);

    const candidate = Object.freeze({
      generation,
      revision: snapshotRevision,
      digest: snapshotDigest,
      modules,
    });
    const maximumView = freezeResult({
      kind: "RuntimeViewV1",
      sessionId: this.#session.sessionId,
      connectionGeneration: this.#session.connectionGeneration,
      stale: false,
      ...candidate,
      pending: MAX_PENDING,
      indeterminate: MAX_PENDING,
      recoveryRequired: MAX_PENDING,
      previousSnapshotRetained: true,
    });
    const projectedBytes = utf8Bytes(JSON.stringify(maximumView));
    if (projectedBytes > MAX_VIEW_BYTES) {
      fail(ERROR_CODES.VIEW_TOO_LARGE, "projected runtime view exceeds 1 MiB", {
        projectedBytes,
        maxBytes: MAX_VIEW_BYTES,
      });
    }

    this.#previousSnapshot = this.#snapshot;
    this.#snapshot = candidate;
    return this.readView();
  }

  readView() {
    this.#requireSession();
    const common = {
      kind: "RuntimeViewV1",
      sessionId: this.#session.sessionId,
      connectionGeneration: this.#session.connectionGeneration,
      pending: this.#pending.size,
      indeterminate: this.#indeterminateCount(),
      recoveryRequired: this.#recoveryRequiredCount(),
      previousSnapshotRetained: this.#previousSnapshot !== null,
    };
    if (!this.#snapshot) {
      return freezeResult({
        ...common,
        stale: true,
        generation: null,
        revision: null,
        digest: null,
        modules: Object.freeze([]),
      });
    }
    return freezeResult({ ...common, stale: false, ...this.#snapshot });
  }

  async submitRequest(input) {
    requireRecord(input, "input");
    const proposal = buildOperationProposal(input);
    const inputFields = readOwnDataFields(input, "input", ["displayedView"]);
    const displayedView = normalizeDisplayedView(inputFields.displayedView);
    return this.#submit("operation/request", {
      operationId: proposal.operationId,
      displayedView,
      payloadName: "intent",
      payload: proposal,
    });
  }

  async requestStop(input) {
    const inputFields = readOwnDataFields(
      input,
      "input",
      ["operationId", "scope", "displayedView"],
    );
    const operationId = stableId(inputFields.operationId, "operationId");
    requireRecord(inputFields.scope, "scope");
    const scope = snapshotCanonical(inputFields.scope, "scope", { maxBytes: MAX_REQUEST_BYTES });
    const displayedView = normalizeDisplayedView(inputFields.displayedView);
    return this.#submit("runtime/stop", {
      operationId,
      displayedView,
      payloadName: "scope",
      payload: scope,
    });
  }

  reconcile(observation) {
    const session = this.#captureSession();
    const safeObservation = requireRecord(
      snapshotCanonical(observation, "observation", { maxBytes: MAX_REQUEST_BYTES }),
      "observation",
    );
    const operationId = stableId(safeObservation.operationId, "operationId");
    const pending = this.#pending.get(operationId);
    if (!pending) {
      fail(ERROR_CODES.RECONCILIATION_MISMATCH, "observation does not match a pending operation");
    }
    if (pending.requestInFlight === true) {
      fail(
        ERROR_CODES.RECONCILIATION_MISMATCH,
        "operation cannot reconcile while its original mutation dispatch is still in flight",
      );
    }
    return this.#reconcileObservation(safeObservation, pending, session);
  }

  pauseReconciliation() {
    this.#cancelReconciliationTimer();
  }

  async reconcilePending({ force = false } = {}) {
    if (this.#closing) {
      fail(ERROR_CODES.NOT_CONNECTED, "runtime client is closing");
    }
    this.#requireSession();
    if (typeof force !== "boolean") {
      fail(ERROR_CODES.INVALID_INPUT, "force must be boolean");
    }
    await this.#resumePending({
      ignoreBackoff: force,
      includeRecoveryRequired: force,
    });
    this.#scheduleReconciliation();
    return freezeResult({
      kind: "ReconciliationSummaryV1",
      pending: this.#pending.size,
      indeterminate: this.#indeterminateCount(),
      recoveryRequired: this.#recoveryRequiredCount(),
    });
  }

  async close() {
    return this.#shutdown(true);
  }

  async suspend() {
    return this.#shutdown(false);
  }

  async #shutdown(notifyTransport) {
    if (this.#closePromise) return this.#closePromise;
    const closing = this.#closeInternal(notifyTransport);
    this.#closePromise = closing;
    try {
      return await closing;
    } finally {
      if (this.#closePromise === closing) this.#closePromise = null;
    }
  }

  async #closeInternal(notifyTransport) {
    this.#connectAttempt += 1;
    this.#closing = true;
    const closingSession = this.#session ? Object.freeze({ ...this.#session }) : null;
    this.#cancelReconciliationTimer();
    if (closingSession) {
      this.#markPendingIndeterminate();
      this.#persistBestEffort();
    }
    let closeError = null;
    try {
      if (closingSession && notifyTransport) {
        await this.#transport.close(Object.freeze({ sessionId: closingSession.sessionId }));
      }
    } catch (error) {
      closeError = error;
    } finally {
      if (
        closingSession &&
        this.#session?.sessionId === closingSession.sessionId &&
        this.#session?.connectionGeneration === closingSession.connectionGeneration
      ) {
        this.#session = null;
        this.#snapshot = null;
        this.#previousSnapshot = null;
      }
      await this.#waitForIoDrain();
      this.#closing = false;
    }
    if (closeError instanceof UiControlError) throw closeError;
    if (closeError !== null) {
      fail(ERROR_CODES.BACKEND_UNAVAILABLE, "runtime close acknowledgement is unavailable");
    }
  }

  async #submit(method, input) {
    if (this.#closing) {
      fail(ERROR_CODES.NOT_CONNECTED, "runtime client is closing");
    }
    const capturedSession = this.#captureSession();
    const capturedSnapshot = this.#captureSnapshot();
    const operationId = stableId(input.operationId, "operationId");
    const displayedView = input.displayedView;
    if (
      displayedView.sessionId !== capturedSession.sessionId ||
      displayedView.connectionGeneration !== capturedSession.connectionGeneration ||
      displayedView.generation !== capturedSnapshot.generation ||
      displayedView.revision !== capturedSnapshot.revision ||
      displayedView.digest !== capturedSnapshot.digest
    ) {
      fail(
        ERROR_CODES.STALE_SNAPSHOT,
        "displayed view binding does not match the current runtime session and snapshot",
      );
    }
    const displayedRevision = displayedView.revision;

    const payload = snapshotCanonical(input.payload, input.payloadName, { maxBytes: MAX_REQUEST_BYTES });
    const semantics = Object.freeze({
      schema: REQUEST_SEMANTICS_SCHEMA,
      method,
      operationId,
      displayedView,
      payload,
    });
    const semanticDigest = await canonicalSha256(semantics);
    const prior = this.#pending.get(operationId);
    if (prior) {
      if (prior.semanticDigest !== semanticDigest || prior.method !== method) {
        fail(ERROR_CODES.RECONCILIATION_MISMATCH, "operation identity was reused with changed semantics");
      }
      return prior.acknowledgement;
    }
    if (!this.#captureStillCurrent(capturedSession, capturedSnapshot)) {
      fail(ERROR_CODES.STALE_SNAPSHOT, "runtime session or snapshot changed during request construction");
    }
    if (this.#pending.size >= MAX_PENDING) {
      fail(ERROR_CODES.CAPACITY_EXHAUSTED, "pending operation capacity is exhausted");
    }

    const now = this.#now();
    const entry = {
      method,
      operationId,
      semanticDigest,
      semantics,
      displayedRevision,
      originSessionId: capturedSession.sessionId,
      originConnectionGeneration: capturedSession.connectionGeneration,
      runtimeGeneration: capturedSnapshot.generation,
      accepted: null,
      status: "pending",
      acknowledgement: null,
      createdAtMs: now,
      reconcileAttempts: 0,
      nextReconcileAtMs: now + RECONCILE_BASE_DELAY_MS,
      recoveryRequired: false,
      requestInFlight: false,
    };
    cloneAcknowledgement(entry, "pending", { accepted: null });
    this.#pending.set(operationId, entry);
    try {
      this.#persistPending();
    } catch (error) {
      this.#pending.delete(operationId);
      throw error;
    }

    const request = Object.freeze({
      schema: TRANSPORT_REQUEST_SCHEMA,
      sessionId: entry.originSessionId,
      connectionGeneration: entry.originConnectionGeneration,
      runtimeGeneration: entry.runtimeGeneration,
      runtimeDigest: displayedView.digest,
      displayedRevision,
      operationId,
      semanticDigest,
      [input.payloadName]: payload,
    });

    entry.requestInFlight = true;
    this.#beginIo();
    try {
      let rawResponse;
      try {
        rawResponse = await this.#transport.request(method, request);
      } catch {
        cloneAcknowledgement(entry, "indeterminate", {
          accepted: null,
          errorCode: ERROR_CODES.BACKEND_UNAVAILABLE,
        });
        this.#persistBestEffort();
        this.#scheduleReconciliation();
        return entry.acknowledgement;
      }
      let response;
      try {
        response = requireRecord(
          snapshotCanonical(rawResponse, "request acknowledgement", { maxBytes: MAX_REQUEST_BYTES }),
          "request acknowledgement",
        );
      } catch {
        cloneAcknowledgement(entry, "indeterminate", {
          accepted: null,
          errorCode: ERROR_CODES.PROTOCOL_VIOLATION,
        });
        entry.recoveryRequired = true;
        this.#persistBestEffort();
        fail(ERROR_CODES.PROTOCOL_VIOLATION, "backend acknowledgement must be a record", {
          operationId,
          semanticDigest,
        });
      }

      if (
        response.operationId !== operationId ||
        response.semanticDigest !== semanticDigest ||
        response.method !== method ||
        response.sessionId !== entry.originSessionId ||
        response.connectionGeneration !== entry.originConnectionGeneration ||
        response.runtimeGeneration !== entry.runtimeGeneration
      ) {
        cloneAcknowledgement(entry, "indeterminate", {
          accepted: null,
          errorCode: ERROR_CODES.PROTOCOL_VIOLATION,
        });
        entry.recoveryRequired = true;
        this.#persistBestEffort();
        fail(ERROR_CODES.PROTOCOL_VIOLATION, "backend acknowledgement provenance mismatch", {
          operationId,
          semanticDigest,
        });
      }
      if (response.accepted === false) {
        this.#deletePersistedPending(entry);
        fail(ERROR_CODES.REQUEST_REJECTED, "backend rejected the request", {
          operationId,
          semanticDigest,
        });
      }
      if (response.accepted !== true) {
        cloneAcknowledgement(entry, "indeterminate", {
          accepted: null,
          errorCode: ERROR_CODES.PROTOCOL_VIOLATION,
        });
        entry.recoveryRequired = true;
        this.#persistBestEffort();
        fail(ERROR_CODES.PROTOCOL_VIOLATION, "backend acknowledgement accepted flag is invalid", {
          operationId,
          semanticDigest,
        });
      }

      cloneAcknowledgement(entry, "pending", { accepted: true });
      this.#persistBestEffort();
      this.#scheduleReconciliation();
      return entry.acknowledgement;
    } finally {
      entry.requestInFlight = false;
      this.#endIo();
      // A reconnect may have happened while the mutation acknowledgement was
      // in flight. Only after the original dispatch settles may the operation
      // enter read-only reconciliation.
      this.#scheduleReconciliation();
    }
  }

  #reconcileObservation(observation, pending, session) {
    this.#verifyObservationProvenance(observation, pending, session);
    if (!STATUSES.has(observation.status)) {
      fail(ERROR_CODES.PROTOCOL_VIOLATION, "operation status is not registered");
    }
    const terminal = TERMINAL_STATUSES.has(observation.status);
    if (terminal && observation.terminalObserved !== true) {
      fail(ERROR_CODES.PROTOCOL_VIOLATION, "terminal status requires terminal observation");
    }
    if (!terminal && observation.terminalObserved === true) {
      fail(ERROR_CODES.PROTOCOL_VIOLATION, "non-terminal status cannot claim terminal observation");
    }

    const result = freezeResult({
      kind: "OperationDispositionV1",
      method: pending.method,
      operationId: pending.operationId,
      status: observation.status,
      semanticDigest: pending.semanticDigest,
      terminalObserved: observation.terminalObserved === true,
      outcomeDigest:
        observation.outcomeDigest == null
          ? null
          : requireDigest(observation.outcomeDigest, "outcomeDigest"),
      observedSessionId: session.sessionId,
      observedConnectionGeneration: session.connectionGeneration,
      originSessionId: pending.originSessionId,
      originConnectionGeneration: pending.originConnectionGeneration,
      runtimeGeneration: pending.runtimeGeneration,
    });
    if (terminal) {
      this.#deletePersistedPending(pending);
    } else {
      cloneAcknowledgement(pending, observation.status, { accepted: pending.accepted });
      this.#advanceReconciliation(pending);
      this.#persistBestEffort();
    }
    return result;
  }

  #verifyObservationProvenance(observation, pending, session) {
    if (observation.operationId !== pending.operationId) {
      fail(ERROR_CODES.RECONCILIATION_MISMATCH, "observation operation identity mismatch");
    }
    if (observation.semanticDigest !== pending.semanticDigest) {
      fail(ERROR_CODES.RECONCILIATION_MISMATCH, "observation semantic digest mismatch");
    }
    if (observation.method !== pending.method) {
      fail(ERROR_CODES.RECONCILIATION_MISMATCH, "observation method mismatch");
    }
    if (
      observation.sessionId !== session.sessionId ||
      observation.connectionGeneration !== session.connectionGeneration
    ) {
      fail(ERROR_CODES.RECONCILIATION_MISMATCH, "observation current-session provenance mismatch");
    }
    if (
      observation.originSessionId !== pending.originSessionId ||
      observation.originConnectionGeneration !== pending.originConnectionGeneration ||
      observation.runtimeGeneration !== pending.runtimeGeneration
    ) {
      fail(ERROR_CODES.RECONCILIATION_MISMATCH, "observation operation provenance mismatch");
    }
  }

  #markPendingIndeterminate() {
    for (const entry of this.#pending.values()) {
      if (!TERMINAL_STATUSES.has(entry.status)) {
        cloneAcknowledgement(entry, "indeterminate", {
          accepted: entry.accepted,
          errorCode: ERROR_CODES.BACKEND_UNAVAILABLE,
        });
      }
    }
  }

  async #resumePending({
    ignoreBackoff = false,
    includeRecoveryRequired = false,
  } = {}) {
    if (this.#closing || !this.#session || this.#pending.size === 0) return;
    const session = this.#captureSession();
    const eligible = [];
    const now = this.#now();
    let recoveryChanged = false;
    const candidates = [...this.#pending.values()].sort(
      (left, right) =>
        left.nextReconcileAtMs - right.nextReconcileAtMs ||
        left.createdAtMs - right.createdAtMs ||
        left.operationId.localeCompare(right.operationId),
    );
    for (const entry of candidates) {
      recoveryChanged =
        this.#refreshRecoveryRequirement(entry, now) || recoveryChanged;
      if (entry.requestInFlight === true) continue;
      if (entry.recoveryRequired && !includeRecoveryRequired) continue;
      if (!ignoreBackoff && entry.nextReconcileAtMs > now) continue;
      eligible.push(entry);
      if (eligible.length >= RECONCILE_BATCH_SIZE) break;
    }
    if (recoveryChanged) this.#persistBestEffort();
    if (eligible.length === 0) return;
    await Promise.all(eligible.map((entry) => this.#reconcileEntry(entry, session)));
  }

  async #reconcileEntry(entry, session) {
    this.#beginIo();
    try {
      let observation;
      try {
        observation = await this.#transport.reconcile(
          Object.freeze({
            sessionId: session.sessionId,
            connectionGeneration: session.connectionGeneration,
            method: entry.method,
            operationId: entry.operationId,
            semanticDigest: entry.semanticDigest,
            originSessionId: entry.originSessionId,
            originConnectionGeneration: entry.originConnectionGeneration,
            runtimeGeneration: entry.runtimeGeneration,
          }),
        );
      } catch {
        this.#advanceReconciliation(entry);
        this.#persistBestEffort();
        return;
      }
      if (observation == null) {
        this.#advanceReconciliation(entry);
        this.#persistBestEffort();
        return;
      }
      try {
        const safeObservation = requireRecord(
          snapshotCanonical(observation, "reconciliation observation", {
            maxBytes: MAX_REQUEST_BYTES,
          }),
          "reconciliation observation",
        );
        this.#reconcileObservation(safeObservation, entry, session);
      } catch (error) {
        entry.recoveryRequired = true;
        cloneAcknowledgement(entry, "indeterminate", {
          accepted: entry.accepted,
          errorCode:
            error instanceof UiControlError
              ? error.code
              : ERROR_CODES.PROTOCOL_VIOLATION,
        });
        this.#persistBestEffort();
      }
    } finally {
      this.#endIo();
    }
  }

  #advanceReconciliation(entry) {
    const now = this.#now();
    entry.reconcileAttempts += 1;
    const exponent = Math.min(entry.reconcileAttempts - 1, 16);
    const delay = Math.min(RECONCILE_BASE_DELAY_MS * 2 ** exponent, RECONCILE_MAX_DELAY_MS);
    entry.nextReconcileAtMs = now + delay;
    this.#refreshRecoveryRequirement(entry, now);
  }

  #refreshRecoveryRequirement(entry, now = this.#now()) {
    if (
      !entry.recoveryRequired &&
      (entry.reconcileAttempts >= RECONCILE_AUTO_ATTEMPTS ||
        now - entry.createdAtMs >= RECONCILE_RECOVERY_AGE_MS)
    ) {
      entry.recoveryRequired = true;
      if (PERSISTABLE_STATUSES.has(entry.status)) {
        cloneAcknowledgement(entry, "indeterminate", {
          accepted: entry.accepted,
          errorCode: ERROR_CODES.BACKEND_UNAVAILABLE,
        });
      }
      return true;
    }
    return false;
  }

  #scheduleReconciliation() {
    if (this.#closing || !this.#session || !this.#setTimer) return;
    let due = null;
    const now = this.#now();
    let recoveryChanged = false;
    for (const entry of this.#pending.values()) {
      recoveryChanged =
        this.#refreshRecoveryRequirement(entry, now) || recoveryChanged;
      if (entry.requestInFlight === true) continue;
      if (entry.recoveryRequired) continue;
      if (due === null || entry.nextReconcileAtMs < due) due = entry.nextReconcileAtMs;
    }
    if (recoveryChanged) this.#persistBestEffort();
    if (due === null) {
      this.#cancelReconciliationTimer();
      return;
    }
    if (this.#timer !== null && this.#timerDueAt !== null && this.#timerDueAt <= due) return;
    this.#cancelReconciliationTimer();
    const delay = Math.max(0, due - now);
    const timer = this.#setTimer(() => {
      this.#timer = null;
      this.#timerDueAt = null;
      void this.#resumePending()
        .catch(() => {})
        .finally(() => this.#scheduleReconciliation());
    }, delay);
    timer?.unref?.();
    this.#timer = timer;
    this.#timerDueAt = due;
  }

  #cancelReconciliationTimer() {
    if (this.#timer !== null && this.#clearTimer) {
      this.#clearTimer(this.#timer);
    }
    this.#timer = null;
    this.#timerDueAt = null;
  }

  #restorePending() {
    if (!this.#pendingStore) return;
    let records;
    try {
      records = this.#pendingStore.load();
    } catch (error) {
      if (error instanceof UiControlError) throw error;
      fail(ERROR_CODES.PERSISTENCE_UNAVAILABLE, "pending operation storage load failed");
    }
    if (!Array.isArray(records) || records.length > MAX_PENDING) {
      fail(ERROR_CODES.PERSISTENCE_UNAVAILABLE, "pending operation storage returned invalid entries");
    }
    for (let index = 0; index < records.length; index += 1) {
      let record;
      try {
        record = normalizePendingRecord(records[index], `pending record[${index}]`);
      } catch {
        fail(ERROR_CODES.PERSISTENCE_UNAVAILABLE, "pending operation storage returned invalid entry");
      }
      if (this.#pending.has(record.operationId)) {
        fail(ERROR_CODES.PERSISTENCE_UNAVAILABLE, "pending operation storage contains duplicate identity");
      }
      const now = this.#now();
      const restoredRecoveryRequired =
        record.recoveryRequired === true ||
        record.createdAtMs > now + RECONCILE_CLOCK_FUTURE_SKEW_MS ||
        record.nextReconcileAtMs < record.createdAtMs ||
        record.nextReconcileAtMs >
          now + RECONCILE_MAX_DELAY_MS + RECONCILE_CLOCK_FUTURE_SKEW_MS;
      const entry = {
        ...record,
        nextReconcileAtMs: restoredRecoveryRequired ? now : record.nextReconcileAtMs,
        recoveryRequired: restoredRecoveryRequired,
        semantics: null,
        acknowledgement: null,
        requestInFlight: false,
      };
      cloneAcknowledgement(entry, record.status, {
        accepted: record.accepted,
        errorCode: record.status === "indeterminate" ? ERROR_CODES.BACKEND_UNAVAILABLE : null,
      });
      this.#pending.set(record.operationId, entry);
    }
  }

  #pendingRecords() {
    return [...this.#pending.values()].map((entry) => ({
      method: entry.method,
      operationId: entry.operationId,
      semanticDigest: entry.semanticDigest,
      originSessionId: entry.originSessionId,
      originConnectionGeneration: entry.originConnectionGeneration,
      runtimeGeneration: entry.runtimeGeneration,
      displayedRevision: entry.displayedRevision,
      accepted: entry.accepted,
      status: PERSISTABLE_STATUSES.has(entry.status) ? entry.status : "indeterminate",
      createdAtMs: nonNegativeInteger(entry.createdAtMs, "createdAtMs"),
      reconcileAttempts: nonNegativeInteger(entry.reconcileAttempts, "reconcileAttempts"),
      nextReconcileAtMs: nonNegativeInteger(entry.nextReconcileAtMs, "nextReconcileAtMs"),
      recoveryRequired: entry.recoveryRequired === true,
    }));
  }

  #persistPending() {
    if (!this.#pendingStore) return;
    try {
      this.#pendingStore.save(this.#pendingRecords());
    } catch (error) {
      if (error instanceof UiControlError && error.code === ERROR_CODES.PERSISTENCE_UNAVAILABLE) {
        throw error;
      }
      fail(ERROR_CODES.PERSISTENCE_UNAVAILABLE, "pending operation storage write failed");
    }
  }

  #persistBestEffort() {
    try {
      this.#persistPending();
      return true;
    } catch {
      for (const entry of this.#pending.values()) {
        entry.recoveryRequired = true;
        cloneAcknowledgement(entry, "indeterminate", {
          accepted: entry.accepted,
          errorCode: ERROR_CODES.PERSISTENCE_UNAVAILABLE,
        });
      }
      return false;
    }
  }

  #deletePersistedPending(entry) {
    this.#pending.delete(entry.operationId);
    try {
      this.#persistPending();
    } catch (error) {
      this.#pending.set(entry.operationId, entry);
      entry.recoveryRequired = true;
      cloneAcknowledgement(entry, "indeterminate", {
        accepted: entry.accepted,
        errorCode: ERROR_CODES.PERSISTENCE_UNAVAILABLE,
      });
      throw error;
    }
  }

  #beginIo() {
    this.#activeIo += 1;
  }

  #endIo() {
    if (this.#activeIo <= 0) {
      fail(ERROR_CODES.PROTOCOL_VIOLATION, "runtime client I/O accounting underflow");
    }
    this.#activeIo -= 1;
    if (this.#activeIo === 0) {
      const waiters = this.#drainWaiters;
      this.#drainWaiters = [];
      for (const resolve of waiters) resolve();
    }
  }

  #waitForIoDrain() {
    if (this.#activeIo === 0) return Promise.resolve();
    return new Promise((resolve) => this.#drainWaiters.push(resolve));
  }

  #captureSession() {
    this.#requireSession();
    return Object.freeze({ ...this.#session });
  }

  #captureSnapshot() {
    if (!this.#snapshot) {
      fail(ERROR_CODES.STALE_SNAPSHOT, "mutating request requires a coherent runtime snapshot");
    }
    return this.#snapshot;
  }

  #captureStillCurrent(session, snapshot) {
    return Boolean(
      this.#session &&
        this.#snapshot &&
        this.#session.sessionId === session.sessionId &&
        this.#session.connectionGeneration === session.connectionGeneration &&
        this.#snapshot.generation === snapshot.generation &&
        this.#snapshot.revision === snapshot.revision &&
        this.#snapshot.digest === snapshot.digest,
    );
  }

  #now() {
    return nonNegativeInteger(this.#clock(), "clock result");
  }

  #indeterminateCount() {
    let count = 0;
    for (const entry of this.#pending.values()) if (entry.status === "indeterminate") count += 1;
    return count;
  }

  #recoveryRequiredCount() {
    let count = 0;
    for (const entry of this.#pending.values()) if (entry.recoveryRequired === true) count += 1;
    return count;
  }

  #requireSession() {
    if (!this.#session) fail(ERROR_CODES.NOT_CONNECTED, "runtime client is not connected");
  }
}

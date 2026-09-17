import { buildOperationProposal, projectRuntime } from "./control.js";
import {
  ERROR_CODES,
  MAX_REQUEST_BYTES,
  MAX_VIEW_BYTES,
  canonicalSha256,
  fail,
  freezeResult,
  positiveInteger,
  requireDigest,
  requireRecord,
  snapshotCanonical,
  stableId,
  utf8Bytes,
} from "./protocol.js";

const STATUSES = new Set([
  "pending",
  "indeterminate",
  "succeeded",
  "failed",
  "cancelled",
  "rejected",
]);
const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled", "rejected"]);
const MAX_PENDING = 1024;
const MAX_MODULES = 4096;
const REQUEST_SEMANTICS_SCHEMA = "hepta.ui-control.request-semantics.v1";
const TRANSPORT_REQUEST_SCHEMA = "hepta.ui-control.transport-request.v1";

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
    errorCode: extra.errorCode ?? null,
  });
  entry.acknowledgement = acknowledgement;
  entry.status = status;
  if (extra.accepted !== undefined) {
    entry.accepted = extra.accepted;
  }
  return acknowledgement;
}

export class RuntimeClient {
  #transport;
  #session = null;
  #snapshot = null;
  #previousSnapshot = null;
  #pending = new Map();

  constructor({ transport }) {
    requireRecord(transport, "transport");
    for (const method of ["connect", "request", "reconcile", "close"]) {
      if (typeof transport[method] !== "function") {
        fail(ERROR_CODES.INVALID_INPUT, `transport.${method} must be a function`);
      }
    }
    this.#transport = transport;
  }

  async connect(endpointManifest) {
    requireRecord(endpointManifest, "endpointManifest");
    const endpointId = stableId(endpointManifest.endpointId, "endpointId");
    const protocolVersion = positiveInteger(
      endpointManifest.protocolVersion,
      "protocolVersion",
    );
    const manifestDigest = requireDigest(
      endpointManifest.manifestDigest,
      "manifestDigest",
    );

    let observed;
    try {
      observed = requireRecord(
        await this.#transport.connect({ endpointId, protocolVersion, manifestDigest }),
        "connection observation",
      );
    } catch (error) {
      if (error?.code) {
        throw error;
      }
      fail(ERROR_CODES.BACKEND_UNAVAILABLE, "runtime backend is unavailable");
    }
    if (observed.authenticated !== true) {
      fail(ERROR_CODES.UNAUTHENTICATED, "runtime connection is not authenticated");
    }
    if (observed.protocolVersion !== protocolVersion) {
      fail(ERROR_CODES.INCOMPATIBLE_PROTOCOL, "runtime protocol version mismatch", {
        expected: protocolVersion,
        observed: observed.protocolVersion,
      });
    }

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
    await this.#resumePending();

    return freezeResult({
      kind: "RuntimeSessionV1",
      ...this.#session,
      pendingReconciliation: this.#pending.size,
    });
  }

  applySnapshot(snapshot) {
    this.#requireSession();
    requireRecord(snapshot, "snapshot");
    const generation = positiveInteger(snapshot.generation, "generation");
    const snapshotRevision = positiveInteger(snapshot.revision, "revision");
    const snapshotDigest = requireDigest(snapshot.digest, "digest");
    if (snapshot.sessionId !== this.#session.sessionId) {
      fail(ERROR_CODES.PROTOCOL_VIOLATION, "snapshot session identity mismatch");
    }
    if (snapshot.connectionGeneration !== this.#session.connectionGeneration) {
      fail(ERROR_CODES.PROTOCOL_VIOLATION, "snapshot connection generation mismatch");
    }
    if (!Array.isArray(snapshot.modules) || snapshot.modules.length > MAX_MODULES) {
      fail(ERROR_CODES.INVALID_INPUT, "snapshot.modules must be a bounded array");
    }
    if (this.#snapshot) {
      if (generation < this.#snapshot.generation) {
        fail(ERROR_CODES.STALE_SNAPSHOT, "snapshot generation regressed");
      }
      if (
        generation === this.#snapshot.generation &&
        snapshotRevision <= this.#snapshot.revision
      ) {
        fail(ERROR_CODES.STALE_SNAPSHOT, "snapshot revision did not advance");
      }
    }

    const moduleIds = new Set();
    const modules = snapshot.modules.map((module) => {
      const projection = projectRuntime(module);
      if (moduleIds.has(projection.moduleId)) {
        fail(ERROR_CODES.PROTOCOL_VIOLATION, "snapshot contains duplicate module identity");
      }
      moduleIds.add(projection.moduleId);
      return projection;
    });
    Object.freeze(modules);

    const candidate = Object.freeze({
      generation,
      revision: snapshotRevision,
      digest: snapshotDigest,
      modules,
    });
    const projectedBytes = utf8Bytes(JSON.stringify(candidate));
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
    if (!this.#snapshot) {
      return freezeResult({
        kind: "RuntimeViewV1",
        sessionId: this.#session.sessionId,
        connectionGeneration: this.#session.connectionGeneration,
        stale: true,
        generation: null,
        revision: null,
        digest: null,
        modules: Object.freeze([]),
        pending: this.#pending.size,
        indeterminate: this.#indeterminateCount(),
        previousSnapshotRetained: this.#previousSnapshot !== null,
      });
    }
    return freezeResult({
      kind: "RuntimeViewV1",
      sessionId: this.#session.sessionId,
      connectionGeneration: this.#session.connectionGeneration,
      stale: false,
      ...this.#snapshot,
      pending: this.#pending.size,
      indeterminate: this.#indeterminateCount(),
      previousSnapshotRetained: this.#previousSnapshot !== null,
    });
  }

  async submitRequest(input) {
    requireRecord(input, "input");
    const proposal = buildOperationProposal(input);
    const displayedRevision = positiveInteger(
      input.displayedRevision,
      "displayedRevision",
    );
    return this.#submit("operation/request", {
      operationId: proposal.operationId,
      displayedRevision,
      payloadName: "intent",
      payload: proposal,
    });
  }

  async requestStop(input) {
    requireRecord(input, "input");
    const operationId = stableId(input.operationId, "operationId");
    const displayedRevision = positiveInteger(
      input.displayedRevision,
      "displayedRevision",
    );
    const scope = snapshotCanonical(input.scope, "scope", {
      maxBytes: MAX_REQUEST_BYTES,
    });
    return this.#submit("runtime/stop", {
      operationId,
      displayedRevision,
      payloadName: "scope",
      payload: scope,
    });
  }

  reconcile(observation) {
    this.#requireSession();
    requireRecord(observation, "observation");
    const operationId = stableId(observation.operationId, "operationId");
    const pending = this.#pending.get(operationId);
    if (!pending) {
      fail(
        ERROR_CODES.RECONCILIATION_MISMATCH,
        "observation does not match a pending operation",
      );
    }
    this.#verifyObservationProvenance(observation, pending);
    if (!STATUSES.has(observation.status)) {
      fail(ERROR_CODES.PROTOCOL_VIOLATION, "operation status is not registered");
    }
    const terminal = TERMINAL_STATUSES.has(observation.status);
    if (terminal && observation.terminalObserved !== true) {
      fail(
        ERROR_CODES.PROTOCOL_VIOLATION,
        "terminal status requires terminal observation",
      );
    }
    if (!terminal && observation.terminalObserved === true) {
      fail(
        ERROR_CODES.PROTOCOL_VIOLATION,
        "non-terminal status cannot claim terminal observation",
      );
    }

    const result = freezeResult({
      kind: "OperationDispositionV1",
      method: pending.method,
      operationId,
      status: observation.status,
      semanticDigest: pending.semanticDigest,
      terminalObserved: observation.terminalObserved === true,
      outcomeDigest:
        observation.outcomeDigest == null
          ? null
          : requireDigest(observation.outcomeDigest, "outcomeDigest"),
      observedSessionId: this.#session.sessionId,
      observedConnectionGeneration: this.#session.connectionGeneration,
      originSessionId: pending.originSessionId,
      originConnectionGeneration: pending.originConnectionGeneration,
      runtimeGeneration: pending.runtimeGeneration,
    });
    if (terminal) {
      this.#pending.delete(operationId);
    } else {
      cloneAcknowledgement(pending, observation.status, {
        accepted: pending.accepted,
      });
    }
    return result;
  }

  async close() {
    if (!this.#session) {
      return;
    }
    const closingSession = this.#session;
    this.#markPendingIndeterminate();
    try {
      await this.#transport.close({ sessionId: closingSession.sessionId });
    } finally {
      this.#session = null;
      this.#snapshot = null;
      this.#previousSnapshot = null;
    }
  }

  async #submit(method, input) {
    this.#requireSession();
    if (!this.#snapshot) {
      fail(
        ERROR_CODES.STALE_SNAPSHOT,
        "mutating request requires a coherent runtime snapshot",
      );
    }
    const operationId = stableId(input.operationId, "operationId");
    const displayedRevision = positiveInteger(
      input.displayedRevision,
      "displayedRevision",
    );
    if (displayedRevision !== this.#snapshot.revision) {
      fail(ERROR_CODES.STALE_SNAPSHOT, "displayed revision is stale");
    }

    const payload = snapshotCanonical(input.payload, input.payloadName, {
      maxBytes: MAX_REQUEST_BYTES,
    });
    const semantics = Object.freeze({
      schema: REQUEST_SEMANTICS_SCHEMA,
      method,
      operationId,
      displayedRevision,
      payload,
    });
    const semanticDigest = await canonicalSha256(semantics);
    const prior = this.#pending.get(operationId);
    if (prior) {
      if (prior.semanticDigest !== semanticDigest || prior.method !== method) {
        fail(
          ERROR_CODES.RECONCILIATION_MISMATCH,
          "operation identity was reused with changed semantics",
        );
      }
      return prior.acknowledgement;
    }
    if (this.#pending.size >= MAX_PENDING) {
      fail(ERROR_CODES.CAPACITY_EXHAUSTED, "pending operation capacity is exhausted");
    }

    const entry = {
      method,
      operationId,
      semanticDigest,
      semantics,
      displayedRevision,
      originSessionId: this.#session.sessionId,
      originConnectionGeneration: this.#session.connectionGeneration,
      runtimeGeneration: this.#snapshot.generation,
      accepted: null,
      status: "pending",
      acknowledgement: null,
    };
    cloneAcknowledgement(entry, "pending", { accepted: null });
    this.#pending.set(operationId, entry);

    const request = {
      schema: TRANSPORT_REQUEST_SCHEMA,
      sessionId: this.#session.sessionId,
      connectionGeneration: this.#session.connectionGeneration,
      runtimeGeneration: this.#snapshot.generation,
      displayedRevision,
      operationId,
      semanticDigest,
      [input.payloadName]: payload,
    };

    let rawResponse;
    try {
      rawResponse = await this.#transport.request(method, request);
    } catch {
      return cloneAcknowledgement(entry, "indeterminate", {
        accepted: null,
        errorCode: ERROR_CODES.BACKEND_UNAVAILABLE,
      });
    }
    let response;
    try {
      response = requireRecord(rawResponse, "request acknowledgement");
    } catch {
      cloneAcknowledgement(entry, "indeterminate", {
        accepted: null,
        errorCode: ERROR_CODES.PROTOCOL_VIOLATION,
      });
      fail(
        ERROR_CODES.PROTOCOL_VIOLATION,
        "backend acknowledgement must be a record",
        { operationId, semanticDigest },
      );
    }

    if (response.accepted !== true) {
      this.#pending.delete(operationId);
      fail(ERROR_CODES.REQUEST_REJECTED, "backend rejected the request", {
        operationId,
        semanticDigest,
      });
    }
    if (
      response.operationId !== operationId ||
      response.semanticDigest !== semanticDigest ||
      response.method !== method ||
      response.sessionId !== this.#session.sessionId ||
      response.connectionGeneration !== this.#session.connectionGeneration ||
      response.runtimeGeneration !== this.#snapshot.generation
    ) {
      cloneAcknowledgement(entry, "indeterminate", {
        accepted: null,
        errorCode: ERROR_CODES.PROTOCOL_VIOLATION,
      });
      fail(
        ERROR_CODES.PROTOCOL_VIOLATION,
        "backend acknowledgement provenance mismatch",
        { operationId, semanticDigest },
      );
    }

    return cloneAcknowledgement(entry, "pending", { accepted: true });
  }

  #verifyObservationProvenance(observation, pending) {
    if (observation.semanticDigest !== pending.semanticDigest) {
      fail(
        ERROR_CODES.RECONCILIATION_MISMATCH,
        "observation semantic digest mismatch",
      );
    }
    if (observation.method !== pending.method) {
      fail(ERROR_CODES.RECONCILIATION_MISMATCH, "observation method mismatch");
    }
    if (
      observation.sessionId !== this.#session.sessionId ||
      observation.connectionGeneration !== this.#session.connectionGeneration
    ) {
      fail(
        ERROR_CODES.RECONCILIATION_MISMATCH,
        "observation current-session provenance mismatch",
      );
    }
    if (
      observation.originSessionId !== pending.originSessionId ||
      observation.originConnectionGeneration !== pending.originConnectionGeneration ||
      observation.runtimeGeneration !== pending.runtimeGeneration
    ) {
      fail(
        ERROR_CODES.RECONCILIATION_MISMATCH,
        "observation operation provenance mismatch",
      );
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

  async #resumePending() {
    if (!this.#session || this.#pending.size === 0) {
      return;
    }
    for (const entry of [...this.#pending.values()]) {
      let observation;
      try {
        observation = await this.#transport.reconcile({
          sessionId: this.#session.sessionId,
          connectionGeneration: this.#session.connectionGeneration,
          method: entry.method,
          operationId: entry.operationId,
          semanticDigest: entry.semanticDigest,
          originSessionId: entry.originSessionId,
          originConnectionGeneration: entry.originConnectionGeneration,
          runtimeGeneration: entry.runtimeGeneration,
        });
      } catch {
        continue;
      }
      if (observation == null) {
        continue;
      }
      try {
        this.reconcile(observation);
      } catch {
        // Fail closed: an untrusted/malformed reconciliation response never settles work.
      }
    }
  }

  #indeterminateCount() {
    let count = 0;
    for (const entry of this.#pending.values()) {
      if (entry.status === "indeterminate") {
        count += 1;
      }
    }
    return count;
  }

  #requireSession() {
    if (!this.#session) {
      fail(ERROR_CODES.NOT_CONNECTED, "runtime client is not connected");
    }
  }
}

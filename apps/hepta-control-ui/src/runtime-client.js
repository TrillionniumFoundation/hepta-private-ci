const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);
const STATUSES = new Set([
  "pending",
  "indeterminate",
  "succeeded",
  "failed",
  "cancelled",
  "rejected",
]);
const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled", "rejected"]);
const MAX_UNRESOLVED = 1024;
const BINDING_FIELDS = Object.freeze([
  "method",
  "sessionId",
  "connectionGeneration",
  "runtimeGeneration",
  "displayedRevision",
  "snapshotDigest",
  "operationId",
  "semanticDigest",
]);

function record(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

function stableId(value, name) {
  if (typeof value !== "string" || !STABLE_ID.test(value)) {
    throw new TypeError(`${name} must be a bounded stable identifier`);
  }
  return value;
}

function digest(value, name) {
  if (typeof value !== "string" || !DIGEST.test(value) || value === ZERO_DIGEST) {
    throw new TypeError(`${name} must be a non-zero lowercase SHA-256 digest`);
  }
  return value;
}

function revision(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

function frozen(value) {
  return Object.freeze({
    ...value,
    authorityGranted: false,
    directStoreWrite: false,
    terminalAuthority: false,
  });
}

function sameBinding(left, right) {
  return BINDING_FIELDS.every((field) => left[field] === right[field]);
}

export class RuntimeClient {
  #transport;
  #session = null;
  #snapshot = null;
  #pending = new Map();
  #orphaned = new Map();

  constructor({ transport }) {
    record(transport, "transport");
    for (const method of ["connect", "request", "close"]) {
      if (typeof transport[method] !== "function") {
        throw new TypeError(`transport.${method} must be a function`);
      }
    }
    this.#transport = transport;
  }

  async connect(endpointManifest) {
    record(endpointManifest, "endpointManifest");
    if (this.#session) {
      throw new TypeError("runtime client is already connected");
    }
    const endpointId = stableId(endpointManifest.endpointId, "endpointId");
    const protocolVersion = revision(endpointManifest.protocolVersion, "protocolVersion");
    const manifestDigest = digest(endpointManifest.manifestDigest, "manifestDigest");
    const observed = record(
      await this.#transport.connect({ endpointId, protocolVersion, manifestDigest }),
      "connection observation",
    );
    if (observed.authenticated !== true) {
      throw new TypeError("runtime connection is not authenticated");
    }
    if (observed.protocolVersion !== protocolVersion) {
      throw new TypeError("runtime protocol version mismatch");
    }
    this.#session = {
      endpointId,
      protocolVersion,
      manifestDigest,
      sessionId: stableId(observed.sessionId, "sessionId"),
      connectionGeneration: revision(
        observed.connectionGeneration,
        "connectionGeneration",
      ),
    };
    this.#snapshot = null;
    this.#pending = new Map();
    return frozen({
      kind: "RuntimeSessionV1",
      ...this.#session,
      unresolvedPreviousSessionOperations: this.#orphaned.size,
    });
  }

  applySnapshot(snapshot) {
    this.#requireSession();
    record(snapshot, "snapshot");
    const generation = revision(snapshot.generation, "generation");
    const snapshotRevision = revision(snapshot.revision, "revision");
    const snapshotDigest = digest(snapshot.digest, "digest");
    if (snapshot.sessionId !== this.#session.sessionId) {
      throw new TypeError("snapshot session identity mismatch");
    }
    if (snapshot.connectionGeneration !== this.#session.connectionGeneration) {
      throw new TypeError("snapshot connection generation mismatch");
    }
    if (this.#snapshot) {
      if (generation < this.#snapshot.generation) {
        throw new TypeError("snapshot generation regressed");
      }
      if (
        generation === this.#snapshot.generation &&
        snapshotRevision <= this.#snapshot.revision
      ) {
        throw new TypeError("snapshot revision did not advance");
      }
    }
    this.#snapshot = {
      generation,
      revision: snapshotRevision,
      digest: snapshotDigest,
      modules: Object.freeze([...(snapshot.modules ?? [])]),
    };
    return this.readView();
  }

  readView() {
    this.#requireSession();
    if (!this.#snapshot) {
      return frozen({
        kind: "RuntimeViewV1",
        sessionId: this.#session.sessionId,
        connectionGeneration: this.#session.connectionGeneration,
        stale: true,
        generation: null,
        revision: null,
        digest: null,
        modules: Object.freeze([]),
        pending: this.#pending.size,
        unresolvedPreviousSessionOperations: this.#orphaned.size,
      });
    }
    return frozen({
      kind: "RuntimeViewV1",
      sessionId: this.#session.sessionId,
      connectionGeneration: this.#session.connectionGeneration,
      stale: false,
      ...this.#snapshot,
      pending: this.#pending.size,
      unresolvedPreviousSessionOperations: this.#orphaned.size,
    });
  }

  async submitRequest(input) {
    return this.#submit("operation/request", input);
  }

  async requestStop(input) {
    return this.#submit("runtime/stop", input);
  }

  reconcile(observation) {
    this.#requireSession();
    record(observation, "observation");
    const operationId = stableId(observation.operationId, "operationId");
    const current = this.#pending.get(operationId);
    const orphaned = this.#orphaned.get(operationId);
    const entry = current ?? orphaned;
    if (!entry) {
      throw new TypeError("observation does not match an unresolved operation");
    }
    const binding = this.#observationBinding(observation);
    if (!sameBinding(entry.binding, binding)) {
      throw new TypeError("observation binding does not match the admitted operation");
    }
    if (!STATUSES.has(observation.status)) {
      throw new TypeError("operation status is not registered");
    }
    const terminal = TERMINAL_STATUSES.has(observation.status);
    if (terminal !== (observation.terminalObserved === true)) {
      throw new TypeError("terminal status and terminal observation disagree");
    }
    const result = frozen({
      kind: "OperationDispositionV1",
      ...entry.binding,
      status: observation.status,
      terminalObserved: observation.terminalObserved === true,
      outcomeDigest:
        observation.outcomeDigest == null
          ? null
          : digest(observation.outcomeDigest, "outcomeDigest"),
    });
    if (terminal) {
      this.#pending.delete(operationId);
      this.#orphaned.delete(operationId);
    }
    return result;
  }

  async close() {
    if (!this.#session) {
      return;
    }
    await this.#transport.close({
      sessionId: this.#session.sessionId,
      connectionGeneration: this.#session.connectionGeneration,
    });
    for (const [operationId, entry] of this.#pending) {
      const existing = this.#orphaned.get(operationId);
      if (existing && !sameBinding(existing.binding, entry.binding)) {
        throw new TypeError("operation identity collides across unresolved sessions");
      }
      this.#orphaned.set(operationId, entry);
    }
    this.#pending = new Map();
    this.#session = null;
    this.#snapshot = null;
  }

  async #submit(method, input) {
    this.#requireSession();
    if (!this.#snapshot) {
      throw new TypeError("mutating request requires a coherent runtime snapshot");
    }
    record(input, "input");
    const operationId = stableId(input.operationId, "operationId");
    const semanticDigest = digest(input.semanticDigest, "semanticDigest");
    const displayedRevision = revision(input.displayedRevision, "displayedRevision");
    if (displayedRevision !== this.#snapshot.revision) {
      throw new TypeError("displayed revision is stale");
    }
    const binding = Object.freeze({
      method,
      sessionId: this.#session.sessionId,
      connectionGeneration: this.#session.connectionGeneration,
      runtimeGeneration: this.#snapshot.generation,
      displayedRevision,
      snapshotDigest: this.#snapshot.digest,
      operationId,
      semanticDigest,
    });
    const prior = this.#pending.get(operationId);
    if (prior) {
      if (!sameBinding(prior.binding, binding)) {
        throw new TypeError("operation identity was reused with changed semantics");
      }
      return prior.acknowledgement;
    }
    if (this.#orphaned.has(operationId)) {
      throw new TypeError(
        "operation identity belongs to an unresolved previous session and must be reconciled",
      );
    }
    if (this.#pending.size + this.#orphaned.size >= MAX_UNRESOLVED) {
      throw new TypeError("unresolved operation capacity is exhausted");
    }
    const response = record(
      await this.#transport.request(method, binding),
      "request acknowledgement",
    );
    if (response.accepted !== true) {
      throw new TypeError("backend rejected the request");
    }
    const responseBinding = this.#observationBinding(response);
    if (!sameBinding(binding, responseBinding)) {
      throw new TypeError("backend acknowledgement binding mismatch");
    }
    const acknowledgement = frozen({
      kind: "OperationAcknowledgementV1",
      ...binding,
      status: "pending",
      accepted: true,
    });
    this.#pending.set(operationId, { binding, acknowledgement });
    return acknowledgement;
  }

  #observationBinding(value) {
    return {
      method: stableId(value.method, "method"),
      sessionId: stableId(value.sessionId, "sessionId"),
      connectionGeneration: revision(
        value.connectionGeneration,
        "connectionGeneration",
      ),
      runtimeGeneration: revision(value.runtimeGeneration, "runtimeGeneration"),
      displayedRevision: revision(value.displayedRevision, "displayedRevision"),
      snapshotDigest: digest(value.snapshotDigest, "snapshotDigest"),
      operationId: stableId(value.operationId, "operationId"),
      semanticDigest: digest(value.semanticDigest, "semanticDigest"),
    };
  }

  #requireSession() {
    if (!this.#session) {
      throw new TypeError("runtime client is not connected");
    }
  }
}

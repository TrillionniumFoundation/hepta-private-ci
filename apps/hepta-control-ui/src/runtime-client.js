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
const MAX_PENDING = 1024;

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

export class RuntimeClient {
  #transport;
  #session = null;
  #snapshot = null;
  #pending = new Map();

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
    const endpointId = stableId(endpointManifest.endpointId, "endpointId");
    const protocolVersion = revision(
      endpointManifest.protocolVersion,
      "protocolVersion",
    );
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
    return frozen({ kind: "RuntimeSessionV1", ...this.#session });
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
        stale: true,
        generation: null,
        revision: null,
        digest: null,
        modules: Object.freeze([]),
        pending: this.#pending.size,
      });
    }
    return frozen({
      kind: "RuntimeViewV1",
      sessionId: this.#session.sessionId,
      stale: false,
      ...this.#snapshot,
      pending: this.#pending.size,
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
    const pending = this.#pending.get(operationId);
    if (!pending) {
      throw new TypeError("observation does not match a pending operation");
    }
    if (observation.semanticDigest !== pending.semanticDigest) {
      throw new TypeError("observation semantic digest mismatch");
    }
    if (!STATUSES.has(observation.status)) {
      throw new TypeError("operation status is not registered");
    }
    const terminal = ["succeeded", "failed", "cancelled", "rejected"].includes(
      observation.status,
    );
    if (terminal && observation.terminalObserved !== true) {
      throw new TypeError("terminal status requires terminal observation");
    }
    const result = frozen({
      kind: "OperationDispositionV1",
      operationId,
      status: observation.status,
      semanticDigest: pending.semanticDigest,
      terminalObserved: observation.terminalObserved === true,
      outcomeDigest:
        observation.outcomeDigest == null
          ? null
          : digest(observation.outcomeDigest, "outcomeDigest"),
    });
    if (terminal) {
      this.#pending.delete(operationId);
    }
    return result;
  }

  async close() {
    if (!this.#session) {
      return;
    }
    await this.#transport.close({ sessionId: this.#session.sessionId });
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
    const displayedRevision = revision(
      input.displayedRevision,
      "displayedRevision",
    );
    if (displayedRevision !== this.#snapshot.revision) {
      throw new TypeError("displayed revision is stale");
    }
    const prior = this.#pending.get(operationId);
    if (prior) {
      if (prior.semanticDigest !== semanticDigest) {
        throw new TypeError("operation identity was reused with changed semantics");
      }
      return prior.acknowledgement;
    }
    if (this.#pending.size >= MAX_PENDING) {
      throw new TypeError("pending operation capacity is exhausted");
    }
    const response = record(
      await this.#transport.request(method, {
        sessionId: this.#session.sessionId,
        connectionGeneration: this.#session.connectionGeneration,
        runtimeGeneration: this.#snapshot.generation,
        displayedRevision,
        operationId,
        semanticDigest,
      }),
      "request acknowledgement",
    );
    if (response.accepted !== true) {
      throw new TypeError("backend rejected the request");
    }
    if (
      response.operationId !== operationId ||
      response.semanticDigest !== semanticDigest
    ) {
      throw new TypeError("backend acknowledgement identity mismatch");
    }
    const acknowledgement = frozen({
      kind: "OperationAcknowledgementV1",
      method,
      operationId,
      semanticDigest,
      status: "pending",
      accepted: true,
    });
    this.#pending.set(operationId, { semanticDigest, acknowledgement });
    return acknowledgement;
  }

  #requireSession() {
    if (!this.#session) {
      throw new TypeError("runtime client is not connected");
    }
  }
}

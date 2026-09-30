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

function snapshotModules(modules) {
  if (!Array.isArray(modules) || modules.length > 256)
    throw new TypeError("snapshot modules must be a bounded array");
  let nodes = 0;
  let bytes = 0;
  function clone(value, depth) {
    if (++nodes > 4096 || depth > 8)
      throw new TypeError("snapshot modules exceed structural limits");
    if (value === null || typeof value === "boolean") return value;
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string") {
      bytes += new TextEncoder().encode(value).byteLength;
      if (bytes > 65536)
        throw new TypeError("snapshot modules exceed byte limit");
      return value;
    }
    if (Array.isArray(value)) {
      if (
        value.length > 256 ||
        Object.getPrototypeOf(value) !== Array.prototype ||
        Reflect.ownKeys(value).length !== value.length + 1
      ) {
        throw new TypeError(
          "snapshot module array exceeds limit or contains non-data fields",
        );
      }
      const copied = [];
      for (let index = 0; index < value.length; index++) {
        const item = Object.getOwnPropertyDescriptor(value, String(index));
        if (!item || !Object.hasOwn(item, "value") || !item.enumerable) {
          throw new TypeError(
            "snapshot module arrays must contain own data properties",
          );
        }
        copied.push(clone(item.value, depth + 1));
      }
      return Object.freeze(copied);
    }
    if (
      value === null ||
      typeof value !== "object" ||
      (Object.getPrototypeOf(value) !== Object.prototype &&
        Object.getPrototypeOf(value) !== null)
    ) {
      throw new TypeError("snapshot module fields must be JSON data");
    }
    const descriptors = Object.getOwnPropertyDescriptors(value);
    const keys = Reflect.ownKeys(descriptors);
    if (keys.length > 256)
      throw new TypeError("snapshot module object exceeds limit");
    return Object.freeze(
      Object.fromEntries(
        keys.map((key) => {
          const field = descriptors[key];
          if (
            typeof key !== "string" ||
            !Object.hasOwn(field, "value") ||
            !field.enumerable
          ) {
            throw new TypeError(
              "snapshot module fields must be own data properties",
            );
          }
          bytes += new TextEncoder().encode(key).byteLength;
          if (bytes > 65536)
            throw new TypeError("snapshot modules exceed byte limit");
          return [key, clone(field.value, depth + 1)];
        }),
      ),
    );
  }
  return clone(modules, 0);
}

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
  if (
    typeof value !== "string" ||
    !DIGEST.test(value) ||
    value === ZERO_DIGEST
  ) {
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
  #connectionAttempt = 0;
  #closing = null;

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
    const attempt = ++this.#connectionAttempt;
    record(endpointManifest, "endpointManifest");
    const endpointId = stableId(endpointManifest.endpointId, "endpointId");
    const protocolVersion = revision(
      endpointManifest.protocolVersion,
      "protocolVersion",
    );
    const manifestDigest = digest(
      endpointManifest.manifestDigest,
      "manifestDigest",
    );
    if (this.#closing) await this.#closing;
    if (attempt !== this.#connectionAttempt)
      throw new TypeError("runtime connection attempt was superseded");
    const observed = record(
      await this.#transport.connect({
        endpointId,
        protocolVersion,
        manifestDigest,
      }),
      "connection observation",
    );
    if (attempt !== this.#connectionAttempt)
      throw new TypeError("runtime connection attempt was superseded");
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
      modules: snapshotModules(snapshot.modules ?? []),
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
    if (pending.session !== this.#session) {
      throw new TypeError(
        "pending operation belongs to a previous runtime connection",
      );
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
    this.#connectionAttempt++;
    if (this.#closing) return this.#closing;
    if (!this.#session) {
      return;
    }
    const session = this.#session;
    this.#session = null;
    this.#snapshot = null;
    const closing = Promise.resolve().then(() =>
      this.#transport.close(
        Object.freeze({
          sessionId: session.sessionId,
          connectionGeneration: session.connectionGeneration,
        }),
      ),
    );
    this.#closing = closing;
    await closing;
    if (this.#closing === closing) this.#closing = null;
  }

  async #submit(method, input) {
    this.#requireSession();
    if (!this.#snapshot) {
      throw new TypeError(
        "mutating request requires a coherent runtime snapshot",
      );
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
      if (prior.semanticDigest !== semanticDigest || prior.method !== method) {
        throw new TypeError(
          "operation identity was reused with changed semantics",
        );
      }
      if (prior.session !== this.#session) {
        throw new TypeError(
          "pending operation belongs to a previous runtime connection",
        );
      }
      return prior.acknowledgement;
    }
    if (this.#pending.size >= MAX_PENDING) {
      throw new TypeError("pending operation capacity is exhausted");
    }
    const session = this.#session;
    const request = Object.freeze({
      sessionId: session.sessionId,
      connectionGeneration: session.connectionGeneration,
      runtimeGeneration: this.#snapshot.generation,
      displayedRevision,
      operationId,
      semanticDigest,
    });
    // Reserve identity and capacity before crossing the asynchronous boundary.
    // A failed transport can have delivered the request, so its reservation
    // remains until a backend observation reconciles the operation.
    const pending = { semanticDigest, method, session, acknowledgement: null };
    const acknowledgement = Promise.resolve().then(async () => {
      const response = record(
        await this.#transport.request(method, request),
        "request acknowledgement",
      );
      if (this.#session !== session) {
        throw new TypeError(
          "runtime connection changed while awaiting acknowledgement",
        );
      }
      if (response.accepted !== true) {
        throw new TypeError("backend rejected the request");
      }
      if (
        response.operationId !== operationId ||
        response.semanticDigest !== semanticDigest
      ) {
        throw new TypeError("backend acknowledgement identity mismatch");
      }
      return frozen({
        kind: "OperationAcknowledgementV1",
        method,
        operationId,
        semanticDigest,
        status: "pending",
        accepted: true,
      });
    });
    pending.acknowledgement = acknowledgement;
    this.#pending.set(operationId, pending);
    return acknowledgement;
  }

  #requireSession() {
    if (!this.#session) {
      throw new TypeError("runtime client is not connected");
    }
  }
}

import { canonicalSha256 } from "./canonical.js";
import { buildOperationProposal, projectRuntime } from "./control.js";
import {
  UI_CONTROL_ERROR_CODES as ERROR,
  UiControlError,
  uiControlError,
} from "./errors.js";

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
const TERMINAL_STATUSES = new Set([
  "succeeded",
  "failed",
  "cancelled",
  "rejected",
]);
const MAX_PENDING = 1024;
const MAX_MODULES = 4096;
const MAX_RENDERED_VIEW_BYTES = 1024 * 1024;
const UTF8 = new TextEncoder();

function record(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    throw new TypeError(`${name} must be a plain object`);
  }
  return value;
}

function exactRecord(value, expectedKeys, name) {
  record(value, name);
  const descriptors = Object.getOwnPropertyDescriptors(value);
  const keys = Reflect.ownKeys(descriptors);
  if (
    keys.length !== expectedKeys.length ||
    keys.some((key) => typeof key !== "string") ||
    expectedKeys.some((key) => !Object.hasOwn(descriptors, key))
  ) {
    throw new TypeError(`${name} contains missing or unknown fields`);
  }
  const result = Object.create(null);
  for (const key of expectedKeys) {
    const descriptor = descriptors[key];
    if (!Object.hasOwn(descriptor, "value") || descriptor.enumerable !== true) {
      throw new TypeError(
        `${name}.${key} must be an enumerable own data property`,
      );
    }
    result[key] = descriptor.value;
  }
  return Object.freeze(result);
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

function validated(code, message, call) {
  try {
    return call();
  } catch (cause) {
    if (cause instanceof UiControlError) {
      throw cause;
    }
    if (cause instanceof TypeError) {
      throw uiControlError(code, message, { cause });
    }
    throw cause;
  }
}

function backendError(message, cause, details) {
  return uiControlError(ERROR.BACKEND_UNAVAILABLE, message, {
    cause,
    details,
  });
}

function stopScope(value) {
  const scope = exactRecord(value, ["subjectId"], "scope");
  return Object.freeze({
    subjectId: stableId(scope.subjectId, "scope.subjectId"),
  });
}

function requestAcknowledgement(entry, status, accepted) {
  return frozen({
    kind: "OperationAcknowledgementV1",
    method: entry.method,
    requestKind: entry.requestKind,
    operationId: entry.operationId,
    semanticDigest: entry.semanticDigest,
    status,
    accepted,
    terminalObserved: false,
  });
}

export class RuntimeClient {
  #transport;
  #digestSemantic;
  #session = null;
  #snapshots = [];
  #pending = new Map();

  constructor({ transport, digestSemantic = canonicalSha256 }) {
    record(transport, "transport");
    for (const method of ["connect", "request", "close"]) {
      if (typeof transport[method] !== "function") {
        throw new TypeError(`transport.${method} must be a function`);
      }
    }
    if (typeof digestSemantic !== "function") {
      throw new TypeError("digestSemantic must be a function");
    }
    this.#transport = transport;
    this.#digestSemantic = digestSemantic;
  }

  async connect(endpointManifest) {
    const manifest = validated(
      ERROR.INVALID_INPUT,
      "endpoint manifest is invalid",
      () =>
        exactRecord(
          endpointManifest,
          ["endpointId", "protocolVersion", "manifestDigest"],
          "endpointManifest",
        ),
    );
    const endpointId = validated(
      ERROR.INVALID_INPUT,
      "endpointId is invalid",
      () => stableId(manifest.endpointId, "endpointId"),
    );
    const protocolVersion = validated(
      ERROR.INVALID_INPUT,
      "protocolVersion is invalid",
      () => revision(manifest.protocolVersion, "protocolVersion"),
    );
    const manifestDigest = validated(
      ERROR.INVALID_INPUT,
      "manifestDigest is invalid",
      () => digest(manifest.manifestDigest, "manifestDigest"),
    );

    let rawObservation;
    try {
      rawObservation = await this.#transport.connect({
        endpointId,
        protocolVersion,
        manifestDigest,
      });
    } catch (cause) {
      throw backendError("runtime connection failed", cause);
    }
    const observed = validated(
      ERROR.PROTOCOL_VIOLATION,
      "connection observation is invalid",
      () =>
        exactRecord(
          rawObservation,
          [
            "authenticated",
            "sessionId",
            "connectionGeneration",
            "protocolVersion",
          ],
          "connection observation",
        ),
    );
    if (observed.authenticated !== true) {
      throw uiControlError(
        ERROR.UNAUTHENTICATED,
        "runtime connection is not authenticated",
      );
    }
    if (observed.protocolVersion !== protocolVersion) {
      throw uiControlError(
        ERROR.INCOMPATIBLE_PROTOCOL,
        "runtime protocol version mismatch",
        {
          details: {
            expected: protocolVersion,
            observed: observed.protocolVersion,
          },
        },
      );
    }

    this.#session = Object.freeze({
      endpointId,
      protocolVersion,
      manifestDigest,
      sessionId: validated(
        ERROR.PROTOCOL_VIOLATION,
        "connection session identity is invalid",
        () => stableId(observed.sessionId, "sessionId"),
      ),
      connectionGeneration: validated(
        ERROR.PROTOCOL_VIOLATION,
        "connection generation is invalid",
        () =>
          revision(
            observed.connectionGeneration,
            "connectionGeneration",
          ),
      ),
    });
    this.#snapshots = [];
    return frozen({ kind: "RuntimeSessionV1", ...this.#session });
  }

  applySnapshot(snapshot) {
    this.#requireSession();
    const input = validated(
      ERROR.PROTOCOL_VIOLATION,
      "runtime snapshot is invalid",
      () =>
        exactRecord(
          snapshot,
          [
            "sessionId",
            "connectionGeneration",
            "generation",
            "revision",
            "digest",
            "modules",
          ],
          "snapshot",
        ),
    );
    const generation = validated(
      ERROR.PROTOCOL_VIOLATION,
      "snapshot generation is invalid",
      () => revision(input.generation, "generation"),
    );
    const snapshotRevision = validated(
      ERROR.PROTOCOL_VIOLATION,
      "snapshot revision is invalid",
      () => revision(input.revision, "revision"),
    );
    const snapshotDigest = validated(
      ERROR.PROTOCOL_VIOLATION,
      "snapshot digest is invalid",
      () => digest(input.digest, "digest"),
    );
    if (input.sessionId !== this.#session.sessionId) {
      throw uiControlError(
        ERROR.PROTOCOL_VIOLATION,
        "snapshot session identity mismatch",
      );
    }
    if (input.connectionGeneration !== this.#session.connectionGeneration) {
      throw uiControlError(
        ERROR.PROTOCOL_VIOLATION,
        "snapshot connection generation mismatch",
      );
    }
    if (!Array.isArray(input.modules) || input.modules.length > MAX_MODULES) {
      throw uiControlError(
        ERROR.CAPACITY_EXHAUSTED,
        "snapshot modules must be a bounded array",
      );
    }

    const current = this.#currentSnapshot();
    if (current) {
      if (generation < current.generation) {
        throw uiControlError(
          ERROR.STALE_SNAPSHOT,
          "snapshot generation regressed",
        );
      }
      if (
        generation === current.generation &&
        snapshotRevision <= current.revision
      ) {
        throw uiControlError(
          ERROR.STALE_SNAPSHOT,
          "snapshot revision did not advance",
        );
      }
    }

    const seen = new Set();
    const modules = input.modules.map((module) => {
      const projected = validated(
        ERROR.PROTOCOL_VIOLATION,
        "runtime module projection is invalid",
        () => projectRuntime(module),
      );
      if (seen.has(projected.moduleId)) {
        throw uiControlError(
          ERROR.PROTOCOL_VIOLATION,
          "snapshot contains duplicate module identity",
          { details: { moduleId: projected.moduleId } },
        );
      }
      seen.add(projected.moduleId);
      return projected;
    });
    Object.freeze(modules);

    const next = Object.freeze({
      generation,
      revision: snapshotRevision,
      digest: snapshotDigest,
      modules,
    });
    const renderedBytes = UTF8.encode(
      JSON.stringify(
        frozen({
          kind: "RuntimeViewV1",
          sessionId: this.#session.sessionId,
          stale: false,
          ...next,
          pending: MAX_PENDING,
          indeterminate: MAX_PENDING,
        }),
      ),
    ).byteLength;
    if (renderedBytes > MAX_RENDERED_VIEW_BYTES) {
      throw uiControlError(
        ERROR.CAPACITY_EXHAUSTED,
        "projected runtime view exceeds the 1 MiB presentation limit",
        { details: { renderedBytes, limit: MAX_RENDERED_VIEW_BYTES } },
      );
    }

    this.#snapshots.push(next);
    if (this.#snapshots.length > 2) {
      this.#snapshots.shift();
    }
    return this.readView();
  }

  readView() {
    this.#requireSession();
    const snapshot = this.#currentSnapshot();
    const indeterminate = [...this.#pending.values()].filter(
      (entry) => entry.phase === "indeterminate",
    ).length;
    if (!snapshot) {
      return frozen({
        kind: "RuntimeViewV1",
        sessionId: this.#session.sessionId,
        stale: true,
        generation: null,
        revision: null,
        digest: null,
        modules: Object.freeze([]),
        pending: this.#pending.size,
        indeterminate,
      });
    }
    return frozen({
      kind: "RuntimeViewV1",
      sessionId: this.#session.sessionId,
      stale: false,
      ...snapshot,
      pending: this.#pending.size,
      indeterminate,
    });
  }

  readPending() {
    return Object.freeze(
      [...this.#pending.values()].map((entry) =>
        frozen({
          kind: "PendingOperationV1",
          operationId: entry.operationId,
          requestKind: entry.requestKind,
          semanticDigest: entry.semanticDigest,
          status: entry.phase,
          originConnectionGeneration: entry.originConnectionGeneration,
          runtimeGeneration: entry.runtimeGeneration,
          displayedRevision: entry.displayedRevision,
        }),
      ),
    );
  }

  async submitRequest(input) {
    const request = validated(
      ERROR.INVALID_INPUT,
      "operation request is invalid",
      () => exactRecord(input, ["intent", "displayedRevision"], "input"),
    );
    const displayedRevision = validated(
      ERROR.INVALID_INPUT,
      "displayedRevision is invalid",
      () => revision(request.displayedRevision, "displayedRevision"),
    );
    const proposal = validated(
      ERROR.INVALID_INPUT,
      "operation proposal is invalid",
      () => buildOperationProposal(request.intent),
    );
    if (proposal.expectedRevision !== displayedRevision) {
      throw uiControlError(
        ERROR.STALE_SNAPSHOT,
        "intent expected revision does not match the displayed revision",
      );
    }
    const semantics = Object.freeze({
      kind: "UiControlOperationRequestV1",
      operationId: proposal.operationId,
      subjectId: proposal.subjectId,
      action: proposal.action,
      expectedRevision: proposal.expectedRevision,
    });
    return this.#submit({
      method: "operation/request",
      requestKind: "operation",
      operationId: proposal.operationId,
      displayedRevision,
      semantics,
    });
  }

  async requestStop(input) {
    const request = validated(
      ERROR.INVALID_INPUT,
      "stop request is invalid",
      () =>
        exactRecord(
          input,
          ["operationId", "scope", "displayedRevision"],
          "input",
        ),
    );
    const operationId = validated(
      ERROR.INVALID_INPUT,
      "operationId is invalid",
      () => stableId(request.operationId, "operationId"),
    );
    const displayedRevision = validated(
      ERROR.INVALID_INPUT,
      "displayedRevision is invalid",
      () => revision(request.displayedRevision, "displayedRevision"),
    );
    const scope = validated(
      ERROR.INVALID_INPUT,
      "stop scope is invalid",
      () => stopScope(request.scope),
    );
    const semantics = Object.freeze({
      kind: "UiControlStopRequestV1",
      operationId,
      scope,
      expectedRevision: displayedRevision,
    });
    return this.#submit({
      method: "runtime/stop",
      requestKind: "stop",
      operationId,
      displayedRevision,
      semantics,
    });
  }

  reconcile(observation) {
    this.#requireSession();
    const input = validated(
      ERROR.PROTOCOL_VIOLATION,
      "operation observation is invalid",
      () =>
        exactRecord(
          observation,
          [
            "observerSessionId",
            "originSessionId",
            "originConnectionGeneration",
            "runtimeGeneration",
            "requestKind",
            "operationId",
            "semanticDigest",
            "status",
            "terminalObserved",
            "outcomeDigest",
          ],
          "observation",
        ),
    );
    if (input.observerSessionId !== this.#session.sessionId) {
      throw uiControlError(
        ERROR.PROTOCOL_VIOLATION,
        "observation was not delivered on the current authenticated session",
      );
    }
    const operationId = validated(
      ERROR.PROTOCOL_VIOLATION,
      "observation operation identity is invalid",
      () => stableId(input.operationId, "operationId"),
    );
    const pending = this.#pending.get(operationId);
    if (!pending) {
      throw uiControlError(
        ERROR.RECONCILIATION_REQUIRED,
        "observation does not match a pending operation",
      );
    }
    if (
      input.originSessionId !== pending.originSessionId ||
      input.originConnectionGeneration !== pending.originConnectionGeneration ||
      input.runtimeGeneration !== pending.runtimeGeneration ||
      input.requestKind !== pending.requestKind
    ) {
      throw uiControlError(
        ERROR.PROTOCOL_VIOLATION,
        "observation provenance does not match the pending operation",
      );
    }
    const observationDigest = validated(
      ERROR.PROTOCOL_VIOLATION,
      "observation semantic digest is invalid",
      () => digest(input.semanticDigest, "semanticDigest"),
    );
    if (observationDigest !== pending.semanticDigest) {
      throw uiControlError(
        ERROR.PROTOCOL_VIOLATION,
        "observation semantic digest mismatch",
      );
    }
    if (!STATUSES.has(input.status)) {
      throw uiControlError(
        ERROR.PROTOCOL_VIOLATION,
        "operation status is not registered",
      );
    }
    const terminal = TERMINAL_STATUSES.has(input.status);
    if (terminal !== (input.terminalObserved === true)) {
      throw uiControlError(
        ERROR.PROTOCOL_VIOLATION,
        terminal
          ? "terminal status requires terminal observation"
          : "non-terminal status cannot claim terminal observation",
      );
    }
    if (!terminal && input.outcomeDigest !== null) {
      throw uiControlError(
        ERROR.PROTOCOL_VIOLATION,
        "non-terminal observation cannot include an outcome digest",
      );
    }
    let outcomeDigest = null;
    if (input.outcomeDigest !== null) {
      outcomeDigest = validated(
        ERROR.PROTOCOL_VIOLATION,
        "observation outcome digest is invalid",
        () => digest(input.outcomeDigest, "outcomeDigest"),
      );
    }
    if (
      (input.status === "succeeded" || input.status === "failed") &&
      outcomeDigest === null
    ) {
      throw uiControlError(
        ERROR.PROTOCOL_VIOLATION,
        "terminal success or failure requires an outcome digest",
      );
    }

    pending.phase = input.status;
    pending.acknowledgement = requestAcknowledgement(
      pending,
      input.status,
      input.status === "pending" ? true : null,
    );
    const result = frozen({
      kind: "OperationDispositionV1",
      requestKind: pending.requestKind,
      operationId,
      status: input.status,
      semanticDigest: pending.semanticDigest,
      originConnectionGeneration: pending.originConnectionGeneration,
      runtimeGeneration: pending.runtimeGeneration,
      terminalObserved: input.terminalObserved === true,
      outcomeDigest,
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
    const sessionId = this.#session.sessionId;
    let failure = null;
    try {
      await this.#transport.close({ sessionId });
    } catch (cause) {
      failure = backendError("runtime close was not acknowledged", cause, {
        sessionId,
      });
    } finally {
      this.#session = null;
      this.#snapshots = [];
    }
    if (failure) {
      throw failure;
    }
  }

  async #submit({
    method,
    requestKind,
    operationId,
    displayedRevision,
    semantics,
  }) {
    this.#requireSession();
    const snapshot = this.#currentSnapshot();
    if (!snapshot) {
      throw uiControlError(
        ERROR.STALE_SNAPSHOT,
        "mutating request requires a coherent runtime snapshot",
      );
    }
    if (displayedRevision !== snapshot.revision) {
      throw uiControlError(
        ERROR.STALE_SNAPSHOT,
        "displayed revision is stale",
        {
          details: {
            displayedRevision,
            currentRevision: snapshot.revision,
          },
        },
      );
    }

    let semanticDigest;
    try {
      semanticDigest = digest(
        await this.#digestSemantic(semantics, {
          name: `${requestKind} semantics`,
        }),
        "semanticDigest",
      );
    } catch (cause) {
      if (cause instanceof TypeError) {
        throw uiControlError(
          ERROR.INVALID_INPUT,
          "request semantics could not be canonicalized",
          { cause },
        );
      }
      throw cause;
    }

    const prior = this.#pending.get(operationId);
    if (prior) {
      if (prior.semanticDigest !== semanticDigest) {
        throw uiControlError(
          ERROR.PROTOCOL_VIOLATION,
          "operation identity was reused with changed semantics",
          { details: { operationId } },
        );
      }
      return prior.acknowledgement;
    }
    if (this.#pending.size >= MAX_PENDING) {
      throw uiControlError(
        ERROR.CAPACITY_EXHAUSTED,
        "pending operation capacity is exhausted",
      );
    }

    const entry = {
      method,
      requestKind,
      operationId,
      semanticDigest,
      semantics,
      phase: "sending",
      originSessionId: this.#session.sessionId,
      originConnectionGeneration: this.#session.connectionGeneration,
      runtimeGeneration: snapshot.generation,
      displayedRevision,
      acknowledgement: null,
    };
    entry.acknowledgement = requestAcknowledgement(entry, "pending", null);
    this.#pending.set(operationId, entry);

    const transportPayload = Object.freeze({
      schema: "hepta.ui-control.transport-request.v1",
      sessionId: entry.originSessionId,
      connectionGeneration: entry.originConnectionGeneration,
      runtimeGeneration: entry.runtimeGeneration,
      displayedRevision,
      requestKind,
      operationId,
      semanticDigest,
      request: semantics,
      ...(requestKind === "operation"
        ? { intent: semantics }
        : { scope: semantics.scope }),
    });

    let rawResponse;
    try {
      rawResponse = await this.#transport.request(method, transportPayload);
    } catch (cause) {
      entry.phase = "indeterminate";
      entry.acknowledgement = requestAcknowledgement(
        entry,
        "indeterminate",
        null,
      );
      throw backendError(
        "request outcome is indeterminate and requires reconciliation",
        cause,
        { operationId, semanticDigest, requestKind },
      );
    }

    let response;
    try {
      response = validated(
        ERROR.PROTOCOL_VIOLATION,
        "request acknowledgement is invalid",
        () =>
          exactRecord(
            rawResponse,
            [
              "accepted",
              "operationId",
              "semanticDigest",
              "requestKind",
              "originSessionId",
              "originConnectionGeneration",
              "runtimeGeneration",
            ],
            "request acknowledgement",
          ),
      );
      if (response.accepted !== true && response.accepted !== false) {
        throw uiControlError(
          ERROR.PROTOCOL_VIOLATION,
          "request acknowledgement accepted flag is invalid",
        );
      }
    } catch (cause) {
      entry.phase = "indeterminate";
      entry.acknowledgement = requestAcknowledgement(
        entry,
        "indeterminate",
        null,
      );
      throw cause;
    }

    if (
      response.operationId !== operationId ||
      response.semanticDigest !== semanticDigest ||
      response.requestKind !== requestKind ||
      response.originSessionId !== entry.originSessionId ||
      response.originConnectionGeneration !== entry.originConnectionGeneration ||
      response.runtimeGeneration !== entry.runtimeGeneration
    ) {
      entry.phase = "indeterminate";
      entry.acknowledgement = requestAcknowledgement(
        entry,
        "indeterminate",
        null,
      );
      throw uiControlError(
        ERROR.PROTOCOL_VIOLATION,
        "backend acknowledgement provenance mismatch",
        { details: { operationId, semanticDigest, requestKind } },
      );
    }
    if (response.accepted !== true) {
      this.#pending.delete(operationId);
      throw uiControlError(
        ERROR.REQUEST_REJECTED,
        "backend rejected the request",
        { details: { operationId, semanticDigest, requestKind } },
      );
    }

    entry.phase = "pending";
    entry.acknowledgement = requestAcknowledgement(entry, "pending", true);
    return entry.acknowledgement;
  }

  #currentSnapshot() {
    return this.#snapshots.at(-1) ?? null;
  }

  #requireSession() {
    if (!this.#session) {
      throw uiControlError(
        ERROR.NOT_CONNECTED,
        "runtime client is not connected",
      );
    }
  }
}

import { definitelyNotAccepted } from "./submission-outcome.js";
import {
  assertCanonicalText,
  assertSafeInteger,
  assertSha256,
  assertStableIdentifier,
  constantTimeEqual,
  canonicalJson,
} from "./canonical.js";
import {
  UI_CONTROL_ERROR_CODES,
  asUiControlError,
  uiControlError,
} from "./errors.js";
import {
  ACTIVE_STATUSES,
  TERMINAL_STATUSES,
  assertPlainObject,
  invalid,
  operationMatches,
  publicOperation,
  validateAcknowledgement,
  validateAuditTrace,
} from "./runtime-contract.js";

const MAX_COMPLETED = 1024;

function compareAscii(left, right) {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

export class OperationLedger {
  #pending = new Map();
  #completed = new Map();
  #maxPending;
  #clock;

  constructor({ maxPending, clock }) {
    this.#maxPending = assertSafeInteger(maxPending, "maxPending", { min: 1, max: 4096 });
    this.#clock = clock;
  }

  views() {
    return Object.freeze(
      [...this.#pending.values()]
        .map(publicOperation)
        .sort((left, right) => compareAscii(left.operationId, right.operationId)),
    );
  }

  completedViews() {
    return Object.freeze(
      [...this.#completed.values()]
        .map(publicOperation)
        .sort((left, right) =>
          right.updatedAt - left.updatedAt || compareAscii(left.operationId, right.operationId),
        ),
    );
  }

  async submit(request, signal, dispatch) {
    const completed = this.#completed.get(request.operationId);
    if (completed) {
      this.#assertMatching(completed, request, "completed");
      return publicOperation(completed);
    }
    const prior = this.#pending.get(request.operationId);
    if (prior) {
      this.#assertMatching(prior, request, "reserved");
      return prior.promise;
    }
    if (this.#pending.size >= this.#maxPending) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.PENDING_LIMIT,
        "pending operation capacity is exhausted",
        { retryable: true, details: { maxPending: this.#maxPending } },
      );
    }

    const now = this.#clock();
    const entry = {
      ...request,
      state: "submitting",
      createdAt: now,
      updatedAt: now,
      auditTraceId: null,
      terminalStatus: null,
      outcomeDigest: null,
      promise: null,
    };
    let resolveSubmission;
    let rejectSubmission;
    entry.promise = new Promise((resolve, reject) => {
      resolveSubmission = resolve;
      rejectSubmission = reject;
    });
    this.#pending.set(entry.operationId, entry);
    void this.#dispatch(entry, signal, dispatch).then(resolveSubmission, rejectSubmission);
    return entry.promise;
  }

  async #dispatch(entry, signal, dispatch) {
    try {
      const acknowledgement = await dispatch(entry, signal);
      const terminal = this.#completed.get(entry.operationId);
      if (terminal) return publicOperation(terminal);
      const validated = validateAcknowledgement(entry, acknowledgement);
      entry.state = validated.status === "indeterminate" ? "indeterminate" : "pending";
      entry.auditTraceId = validated.auditTraceId;
      entry.updatedAt = this.#clock();
      entry.promise = Promise.resolve(publicOperation(entry));
      return publicOperation(entry);
    } catch (cause) {
      const terminal = this.#completed.get(entry.operationId);
      if (terminal) return publicOperation(terminal);
      const error = asUiControlError(cause);
      if (definitelyNotAccepted(error)) {
        this.#pending.delete(entry.operationId);
        throw error;
      }
      entry.state = "indeterminate";
      entry.updatedAt = this.#clock();
      const ambiguous = uiControlError(
        UI_CONTROL_ERROR_CODES.AMBIGUOUS_SUBMISSION,
        "control request may have been accepted; recover by operation id before retrying",
        {
          retryable: true,
          details: {
            operationId: entry.operationId,
            semanticDigest: entry.semanticDigest,
          },
          cause: error,
        },
      );
      entry.promise = Promise.reject(ambiguous);
      entry.promise.catch(() => {});
      throw ambiguous;
    }
  }

  find(operationId) {
    return this.#pending.get(operationId) ?? null;
  }

  findCompleted(operationId) {
    return this.#completed.get(operationId) ?? null;
  }

  markMissing(entry) {
    const completed = this.#completed.get(entry.operationId);
    if (completed) return publicOperation(completed);
    if (this.#pending.get(entry.operationId) !== entry) {
      throw invalid("missing lookup references a stale local operation", {
        operationId: entry.operationId,
      });
    }
    if (entry.auditTraceId !== null) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.ACK_MISMATCH,
        "operation lookup contradicted an accepted acknowledgement",
        {
          retryable: true,
          details: {
            operationId: entry.operationId,
            auditTraceId: entry.auditTraceId,
          },
        },
      );
    }
    // Absence is a point-in-time observation: a dispatched request can still
    // commit after this lookup, including from another tab. Only backend-owned
    // admission fencing/tombstones can make non-admission final.
    entry.state = "indeterminate";
    entry.updatedAt = this.#clock();
    entry.promise = Promise.resolve(publicOperation(entry));
    return publicOperation(entry);
  }

  markActive(entry, status, auditTraceId) {
    if (!ACTIVE_STATUSES.has(status)) {
      throw invalid("operation lookup returned an unknown status", { status });
    }
    entry.auditTraceId = validateAuditTrace(entry, auditTraceId);
    entry.updatedAt = this.#clock();
    entry.state = status === "accepted" ? "pending" : status;
    entry.promise = Promise.resolve(publicOperation(entry));
    return publicOperation(entry);
  }

  reconcile(observation) {
    assertPlainObject(observation, "terminal observation");
    const operationId = assertStableIdentifier(observation.operationId, "operationId");
    const semanticDigest = assertSha256(observation.semanticDigest, "semanticDigest");
    if (observation.terminalObserved !== true || !TERMINAL_STATUSES.has(observation.status)) {
      throw invalid("reconciliation requires a registered terminal observation", {
        operationId,
        status: observation.status,
      });
    }
    const auditTraceId = observation.auditTraceId === undefined || observation.auditTraceId === null
      ? null
      : assertStableIdentifier(observation.auditTraceId, "auditTraceId");
    const outcomeDigest = observation.outcomeDigest === undefined || observation.outcomeDigest === null
      ? null
      : assertSha256(observation.outcomeDigest, "outcomeDigest", { allowZero: true });

    const entry = this.#pending.get(operationId);
    if (!entry) {
      const completed = this.#completed.get(operationId);
      if (!completed) {
        throw invalid("terminal observation references an unknown operation", { operationId });
      }
      if (
        !constantTimeEqual(semanticDigest, completed.semanticDigest) ||
        observation.status !== completed.terminalStatus ||
        (auditTraceId !== null && auditTraceId !== completed.auditTraceId) ||
        (outcomeDigest !== null && !constantTimeEqual(outcomeDigest, completed.outcomeDigest ?? ""))
      ) {
        throw uiControlError(
          UI_CONTROL_ERROR_CODES.OPERATION_CONFLICT,
          "terminal replay conflicts with the completed operation identity",
          { details: { operationId } },
        );
      }
      return publicOperation(completed);
    }
    if (!constantTimeEqual(semanticDigest, entry.semanticDigest)) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.OPERATION_CONFLICT,
        "terminal observation semantic digest does not match the operation",
        { details: { operationId } },
      );
    }
    validateAuditTrace(entry, auditTraceId);
    entry.state = "terminal";
    entry.terminalStatus = observation.status;
    entry.auditTraceId = auditTraceId ?? entry.auditTraceId;
    entry.outcomeDigest = outcomeDigest;
    entry.updatedAt = this.#clock();
    entry.promise = Promise.resolve(publicOperation(entry));
    this.#pending.delete(operationId);
    this.#rememberCompleted(entry);
    return publicOperation(entry);
  }

  exportState() {
    return Object.freeze({
      schema: "hepta.ui-control.recovery-state.v1",
      operations: Object.freeze(
        [...this.#pending.values()]
          .map(entry => Object.freeze({
            protocolVersion: entry.protocolVersion,
            method: entry.method,
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
            state: entry.state,
            auditTraceId: entry.auditTraceId,
            createdAt: entry.createdAt,
            updatedAt: entry.updatedAt,
          }))
          .sort((left, right) => compareAscii(left.operationId, right.operationId)),
      ),
    });
  }

  restoreState(state) {
    assertPlainObject(state, "recovery state");
    if (state.schema !== "hepta.ui-control.recovery-state.v1" || !Array.isArray(state.operations)) {
      throw invalid("unsupported recovery state schema");
    }
    if (state.operations.length > this.#maxPending) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.PENDING_LIMIT,
        "recovery state exceeds pending operation capacity",
      );
    }
    // Copy validated data before iteration; accessors and inherited iteration
    // hooks cannot run or substitute the recovery inventory.
    state = JSON.parse(canonicalJson(state, {
      maxArrayLength: this.#maxPending,
      maxEntries: 20 * this.#maxPending + 4,
      maxEncodedBytes: 8192 * this.#maxPending,
    }));
    const restored = new Map();
    for (const operation of state.operations) {
      assertPlainObject(operation, "recovery operation");
      const operationId = assertStableIdentifier(operation.operationId, "operationId");
      if (restored.has(operationId)) {
        throw invalid("recovery state contains a duplicate operation id", { operationId });
      }
      const entry = {
        protocolVersion: assertCanonicalText(operation.protocolVersion, "protocolVersion", {
          maxBytes: 128,
        }),
        method: assertCanonicalText(operation.method, "method", { maxBytes: 64 }),
        operationId,
        semanticDigest: assertSha256(operation.semanticDigest, "semanticDigest"),
        action: assertCanonicalText(operation.action, "action", { maxBytes: 64 }),
        targetId: assertStableIdentifier(operation.targetId, "targetId"),
        reason: assertCanonicalText(operation.reason, "reason", { maxBytes: 1024 }),
        sessionId: assertStableIdentifier(operation.sessionId, "sessionId"),
        connectionGeneration: assertSafeInteger(
          operation.connectionGeneration,
          "connectionGeneration",
          { min: 1 },
        ),
        generation: assertSafeInteger(operation.generation, "generation", { min: 1 }),
        displayedRevision: assertSafeInteger(operation.displayedRevision, "displayedRevision", {
          min: 1,
        }),
        snapshotDigest: assertSha256(operation.snapshotDigest, "snapshotDigest"),
        state: "indeterminate",
        auditTraceId: operation.auditTraceId === null || operation.auditTraceId === undefined
          ? null
          : assertStableIdentifier(operation.auditTraceId, "auditTraceId"),
        createdAt: assertSafeInteger(operation.createdAt, "createdAt", { min: 1 }),
        updatedAt: assertSafeInteger(operation.updatedAt, "updatedAt", { min: 1 }),
        terminalStatus: null,
        outcomeDigest: null,
        promise: null,
      };
      entry.promise = Promise.resolve(publicOperation(entry));
      restored.set(operationId, entry);
    }
    // Import is monotone: a browser restart/retry must not erase reservations,
    // detach a live dispatch promise, or resurrect an already observed terminal.
    const merged = new Map(this.#pending);
    for (const [operationId, entry] of restored) {
      const prior = this.#pending.get(operationId) ?? this.#completed.get(operationId);
      if (prior) this.#assertMatching(prior, entry, "retained");
      else merged.set(operationId, entry);
    }
    if (merged.size > this.#maxPending) {
      throw uiControlError(UI_CONTROL_ERROR_CODES.PENDING_LIMIT,
        "combined recovery state exceeds pending operation capacity");
    }
    this.#pending = merged;
  }

  #assertMatching(entry, request, disposition) {
    if (!operationMatches(entry, request)) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.OPERATION_CONFLICT,
        `operation id is already ${disposition} with different semantics`,
        { details: { operationId: request.operationId } },
      );
    }
  }

  #rememberCompleted(entry) {
    this.#completed.set(entry.operationId, { ...entry, promise: null });
    while (this.#completed.size > MAX_COMPLETED) {
      this.#completed.delete(this.#completed.keys().next().value);
    }
  }
}

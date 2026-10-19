import { UI_CONTROL_ERROR_CODES as C, uiControlError } from "./errors.js";

// Capture operator consent, not authority. RuntimeClient and the server must
// still perform their current authorization and generation checks.
export function captureConfirmation(view, input) {
  const target = view.snapshot?.modules.find(module => module.id === input.targetId);
  if (!view.connected || !view.authenticated || view.stale || !target) {
    throw uiControlError(C.STALE_REVISION, "A current authenticated target is required.", {
      details: { requestDispatched: false },
    });
  }
  return Object.freeze({
    sessionId: view.sessionId,
    identityId: view.identityId,
    permissionRevision: view.permissionRevision,
    connectionGeneration: view.connectionGeneration,
    generation: view.snapshot.generation,
    displayedRevision: view.snapshot.revision,
    snapshotDigest: view.snapshot.semanticDigest,
    targetId: input.targetId,
    targetRevision: target.revision,
    targetDigest: target.semanticDigest,
    action: input.action,
    reason: input.reason,
    operationId: input.operationId,
  });
}

export function assertConfirmation(context, view, input) {
  const now = captureConfirmation(view, input);
  if (!context || Object.keys(now).some(key => context[key] !== now[key])) {
    throw uiControlError(C.STALE_REVISION, "The confirmed context changed; review and confirm again.", {
      retryable: true,
      details: { requestDispatched: false },
    });
  }
}

// Keep an existing selection by ID. Removal must not silently select a new
// target. The initial render alone may choose the first available target.
export function retainedTarget(previous, ids, initialized) {
  if (ids.includes(previous)) return previous;
  return initialized ? "" : (ids[0] ?? "");
}

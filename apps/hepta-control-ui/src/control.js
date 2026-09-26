import {
  assertCanonicalText,
  assertSafeInteger,
  assertSha256,
  assertStableIdentifier,
  canonicalJson,
  digestCanonical,
  parseCanonicalJson,
} from "./canonical.js";
import {
  UI_CONTROL_ERROR_CODES,
  uiControlError,
} from "./errors.js";

export const RUNTIME_STATUSES = Object.freeze([
  "ready",
  "degraded",
  "quarantined",
  "recovering",
  "unavailable",
]);

export const OPERATION_ACTIONS = Object.freeze([
  "request_start",
  "request_quarantine",
  "request_reconcile",
  "request_retry",
  "request_rollback",
  "request_stop",
]);

const STATUS_SET = new Set(RUNTIME_STATUSES);
const ACTION_SET = new Set(OPERATION_ACTIONS);
const MAX_MODULES = 1000;

function invalid(message, details) {
  return uiControlError(UI_CONTROL_ERROR_CODES.INVALID_INPUT, message, {
    details,
  });
}

function assertPlainObject(value, label) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw invalid(`${label} must be an object`, { label });
  }
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    throw invalid(`${label} must be a plain object`, { label });
  }
  return value;
}

function exactKeys(value, expected, label) {
  const keys = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (keys.length !== wanted.length || keys.some((key, index) => key !== wanted[index])) {
    throw invalid(`${label} has unknown or missing fields`, {
      label,
      keys,
      expected: wanted,
    });
  }
}

function normalizeModule(module, index) {
  assertPlainObject(module, `modules[${index}]`);
  exactKeys(module, ["id", "status", "revision", "semanticDigest"], `modules[${index}]`);
  const id = assertStableIdentifier(module.id, `modules[${index}].id`);
  if (!STATUS_SET.has(module.status)) {
    throw invalid(`modules[${index}].status is not registered`, {
      status: module.status,
    });
  }
  const revision = assertSafeInteger(module.revision, `modules[${index}].revision`, {
    min: 1,
  });
  const semanticDigest = assertSha256(
    module.semanticDigest,
    `modules[${index}].semanticDigest`,
  );
  return Object.freeze({ id, status: module.status, revision, semanticDigest });
}

export function projectRuntime(runtime) {
  assertPlainObject(runtime, "runtime");
  exactKeys(runtime, ["generation", "revision", "modules"], "runtime");
  const generation = assertSafeInteger(runtime.generation, "runtime.generation", { min: 1 });
  const revision = assertSafeInteger(runtime.revision, "runtime.revision", { min: 1 });
  if (!Array.isArray(runtime.modules) || runtime.modules.length > MAX_MODULES) {
    throw invalid(`runtime.modules must be an array of at most ${MAX_MODULES} entries`);
  }
  const seen = new Set();
  const modules = runtime.modules.map(normalizeModule).sort((left, right) =>
    left.id.localeCompare(right.id),
  );
  for (const module of modules) {
    if (seen.has(module.id)) {
      throw invalid("runtime.modules contains a duplicate module id", { moduleId: module.id });
    }
    seen.add(module.id);
  }
  const projection = Object.freeze({ generation, revision, modules: Object.freeze(modules) });
  canonicalJson(projection);
  return projection;
}

export async function digestRuntimeProjection(runtime) {
  return digestCanonical("hepta.ui-control.runtime-projection.v1", projectRuntime(runtime));
}

export function buildOperationIntent({
  action,
  targetId,
  generation,
  displayedRevision,
  reason,
}) {
  if (!ACTION_SET.has(action)) {
    throw invalid("operation action is not registered", { action });
  }
  const target = assertStableIdentifier(targetId, "targetId");
  const frozenGeneration = assertSafeInteger(generation, "generation", { min: 1 });
  const frozenRevision = assertSafeInteger(displayedRevision, "displayedRevision", { min: 1 });
  const canonicalReason = assertCanonicalText(reason, "reason", { maxBytes: 1024 });
  return Object.freeze({
    action,
    targetId: target,
    generation: frozenGeneration,
    displayedRevision: frozenRevision,
    reason: canonicalReason,
  });
}

export async function digestOperationIntent(intent) {
  return digestCanonical("hepta.ui-control.operation-intent.v1", intent, {
    maxEncodedBytes: 16 * 1024,
  });
}

export function projectRuntimeFromLocalCanonicalJson(text) {
  return projectRuntime(
    parseCanonicalJson(text, {
      label: "runtime fixture",
      maxDepth: 8,
      maxEntries: 4096,
      maxArrayLength: MAX_MODULES,
      maxStringBytes: 4096,
      maxEncodedBytes: 1024 * 1024,
    }),
  );
}

export function buildLocalOperationProposalFromCanonicalJson(text) {
  const value = parseCanonicalJson(text, {
    label: "operation fixture",
    maxDepth: 4,
    maxEntries: 16,
    maxArrayLength: 8,
    maxStringBytes: 4096,
    maxEncodedBytes: 16 * 1024,
  });
  assertPlainObject(value, "operation fixture");
  exactKeys(
    value,
    ["action", "targetId", "generation", "displayedRevision", "reason"],
    "operation fixture",
  );
  return buildOperationIntent(value);
}

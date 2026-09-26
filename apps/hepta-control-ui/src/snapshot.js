import {
  assertSafeInteger,
  assertSha256,
  assertStableIdentifier,
  canonicalJson,
  digestCanonical,
} from "./canonical.js";
import {
  UI_CONTROL_ERROR_CODES,
  uiControlError,
} from "./errors.js";
import { projectRuntime } from "./control.js";

function invalid(message, details) {
  return uiControlError(UI_CONTROL_ERROR_CODES.INVALID_INPUT, message, { details });
}

function assertPlainObject(value, label) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw invalid(`${label} must be an object`, { label });
  }
  return value;
}

export async function normalizeSnapshot(snapshot, session) {
  assertPlainObject(snapshot, "snapshot");
  assertPlainObject(session, "session");

  const sessionId = assertStableIdentifier(snapshot.sessionId, "snapshot.sessionId");
  const expectedSessionId = assertStableIdentifier(session.sessionId, "session.sessionId");
  if (sessionId !== expectedSessionId) {
    throw invalid("snapshot belongs to a different session", {
      expectedSessionId,
      actualSessionId: sessionId,
    });
  }

  const connectionGeneration = assertSafeInteger(
    snapshot.connectionGeneration,
    "snapshot.connectionGeneration",
    { min: 1 },
  );
  if (connectionGeneration !== session.connectionGeneration) {
    throw uiControlError(
      UI_CONTROL_ERROR_CODES.STALE_GENERATION,
      "snapshot connection generation does not match the authenticated session",
      {
        retryable: true,
        details: {
          expectedConnectionGeneration: session.connectionGeneration,
          actualConnectionGeneration: connectionGeneration,
        },
      },
    );
  }

  const runtime = projectRuntime({
    generation: snapshot.generation,
    revision: snapshot.revision,
    modules: snapshot.modules,
  });
  const computedDigest = await digestCanonical(
    "hepta.ui-control.runtime-snapshot.v1",
    {
      sessionId,
      connectionGeneration,
      generation: runtime.generation,
      revision: runtime.revision,
      modules: runtime.modules,
    },
  );
  const declaredDigest = snapshot.semanticDigest === undefined
    ? computedDigest
    : assertSha256(snapshot.semanticDigest, "snapshot.semanticDigest");
  if (declaredDigest !== computedDigest) {
    throw uiControlError(
      UI_CONTROL_ERROR_CODES.SNAPSHOT_DRIFT,
      "snapshot semantic digest does not match its canonical content",
      {
        details: { declaredDigest, computedDigest },
      },
    );
  }

  const normalized = Object.freeze({
    sessionId,
    connectionGeneration,
    generation: runtime.generation,
    revision: runtime.revision,
    semanticDigest: computedDigest,
    modules: runtime.modules,
    observedAt: typeof snapshot.observedAt === "string" ? snapshot.observedAt : null,
  });
  canonicalJson(normalized);
  return normalized;
}

export function validateSnapshotTransition(previous, next) {
  if (!previous) return next;
  if (next.sessionId !== previous.sessionId) {
    throw uiControlError(
      UI_CONTROL_ERROR_CODES.STALE_GENERATION,
      "snapshot session changed without reconnect",
      { retryable: true },
    );
  }
  if (next.connectionGeneration < previous.connectionGeneration) {
    throw uiControlError(
      UI_CONTROL_ERROR_CODES.STALE_GENERATION,
      "snapshot connection generation regressed",
      { retryable: true },
    );
  }
  if (next.connectionGeneration > previous.connectionGeneration) return next;

  if (next.generation < previous.generation) {
    throw uiControlError(
      UI_CONTROL_ERROR_CODES.STALE_GENERATION,
      "runtime generation regressed",
      {
        retryable: true,
        details: { previous: previous.generation, next: next.generation },
      },
    );
  }
  if (next.generation > previous.generation) return next;

  if (next.revision < previous.revision) {
    throw uiControlError(
      UI_CONTROL_ERROR_CODES.STALE_REVISION,
      "runtime revision regressed",
      {
        retryable: true,
        details: { previous: previous.revision, next: next.revision },
      },
    );
  }
  if (next.revision > previous.revision) return next;

  if (next.semanticDigest !== previous.semanticDigest) {
    throw uiControlError(
      UI_CONTROL_ERROR_CODES.SNAPSHOT_DRIFT,
      "runtime content changed without a revision change",
      {
        details: {
          previousDigest: previous.semanticDigest,
          nextDigest: next.semanticDigest,
        },
      },
    );
  }
  return previous;
}

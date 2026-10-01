import { UI_CONTROL_PERMISSIONS, UI_CONTROL_PROTOCOL_VERSION } from "../src/runtime-client.js";

export const DIGEST_A = "a".repeat(64);
export const DIGEST_B = "b".repeat(64);
export const DIGEST_C = "c".repeat(64);

export function session(overrides = {}) {
  return {
    authenticated: true,
    protocolVersion: UI_CONTROL_PROTOCOL_VERSION,
    sessionId: "session-1",
    connectionGeneration: 1,
    permissionRevision: 1,
    expiresAt: Date.now() + 60 * 60 * 1000,
    revoked: false,
    identityId: "operator-1",
    permissions: Object.values(UI_CONTROL_PERMISSIONS),
    ...overrides,
  };
}

export function snapshot(overrides = {}) {
  return {
    sessionId: "session-1",
    connectionGeneration: 1,
    generation: 7,
    revision: 11,
    modules: [
      {
        id: "runtime.agentd",
        status: "ready",
        revision: 11,
        semanticDigest: DIGEST_A,
      },
      {
        id: "runtime.fleet",
        status: "degraded",
        revision: 9,
        semanticDigest: DIGEST_B,
      },
    ],
    observedAt: "2026-09-26T00:00:00.000Z",
    ...overrides,
  };
}

export function createTransport(overrides = {}) {
  const state = {
    requestCount: 0,
    lookupCount: 0,
    session: session(),
    snapshot: snapshot(),
    operations: new Map(),
  };
  const transport = {
    state,
    async connect() {
      return state.session;
    },
    async readSnapshot() {
      return state.snapshot;
    },
    async request(method, input) {
      state.requestCount += 1;
      const acknowledgement = {
        accepted: true,
        operationId: input.operationId,
        semanticDigest: input.semanticDigest,
        status: "accepted",
        auditTraceId: `audit-${input.operationId}`,
      };
      state.operations.set(input.operationId, {
        found: true,
        operationId: input.operationId,
        semanticDigest: input.semanticDigest,
        status: "pending",
        auditTraceId: acknowledgement.auditTraceId,
      });
      return acknowledgement;
    },
    async lookup(input) {
      state.lookupCount += 1;
      return state.operations.get(input.operationId) ?? { found: false };
    },
    async refresh() {
      state.session = { ...state.session, permissionRevision: state.session.permissionRevision + 1 };
      return state.session;
    },
    async revoke() {},
    async close() {},
    ...overrides,
  };
  return transport;
}

export function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolveValue, rejectValue) => {
    resolve = resolveValue;
    reject = rejectValue;
  });
  return { promise, resolve, reject };
}

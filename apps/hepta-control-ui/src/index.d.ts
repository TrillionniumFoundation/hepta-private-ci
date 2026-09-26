export type RuntimeStatus =
  | "ready"
  | "degraded"
  | "quarantined"
  | "recovering"
  | "unavailable";

export type OperationAction =
  | "request_start"
  | "request_quarantine"
  | "request_reconcile"
  | "request_retry"
  | "request_rollback"
  | "request_stop";

export interface RuntimeModuleProjection {
  readonly id: string;
  readonly status: RuntimeStatus;
  readonly revision: number;
  readonly semanticDigest: string;
}

export interface RuntimeProjection {
  readonly generation: number;
  readonly revision: number;
  readonly modules: readonly RuntimeModuleProjection[];
}

export interface RuntimeSnapshot extends RuntimeProjection {
  readonly sessionId: string;
  readonly connectionGeneration: number;
  readonly semanticDigest: string;
  readonly observedAt: string | null;
}

export interface OperationIntent {
  readonly action: OperationAction;
  readonly targetId: string;
  readonly generation: number;
  readonly displayedRevision: number;
  readonly reason: string;
}

export interface OperationInput {
  readonly operationId: string;
  readonly action?: OperationAction;
  readonly targetId: string;
  readonly displayedRevision: number;
  readonly reason: string;
  readonly semanticDigest?: string;
  readonly signal?: AbortSignal;
}

export interface OperationView {
  readonly operationId: string;
  readonly semanticDigest: string;
  readonly method: string;
  readonly action: OperationAction;
  readonly targetId: string;
  readonly state: string;
  readonly auditTraceId: string | null;
  readonly generation: number;
  readonly displayedRevision: number;
  readonly createdAt: number;
  readonly updatedAt: number;
  readonly terminalStatus: string | null;
  readonly outcomeDigest: string | null;
  readonly authorityGranted: false;
}

export interface RuntimeClientView {
  readonly connected: boolean;
  readonly authenticated: boolean;
  readonly sessionId: string | null;
  readonly connectionGeneration: number | null;
  readonly permissionRevision: number | null;
  readonly permissions: readonly string[];
  readonly expiresAt: number | null;
  readonly stale: boolean;
  readonly snapshot: RuntimeSnapshot | null;
  readonly pending: readonly OperationView[];
  readonly pendingCount: number;
  readonly indeterminateCount: number;
}

export interface UiControlTransport {
  connect(manifest: object, options?: { signal?: AbortSignal }): Promise<object>;
  readSnapshot(input: object, options?: { signal?: AbortSignal }): Promise<object>;
  request(method: string, input: object, options?: { signal?: AbortSignal }): Promise<object>;
  lookup(input: object, options?: { signal?: AbortSignal }): Promise<object>;
  refresh?(session: object, options?: { signal?: AbortSignal }): Promise<object>;
  revoke?(session: object, options?: { signal?: AbortSignal }): Promise<void>;
  close(session: object, options?: { signal?: AbortSignal }): Promise<void>;
}

export const UI_CONTROL_ERROR_CODES: Readonly<Record<string, string>>;
export class UiControlError extends Error {
  readonly code: string;
  readonly retryable: boolean;
  readonly details: Readonly<Record<string, unknown>>;
  constructor(code: string, message: string, options?: object);
  toJSON(): object;
}
export function isUiControlError(value: unknown, code?: string): value is UiControlError;
export function uiControlError(code: string, message: string, options?: object): UiControlError;
export function asUiControlError(value: unknown, code?: string, message?: string, options?: object): UiControlError;

export const DEFAULT_CANONICAL_LIMITS: Readonly<Record<string, number>>;
export function canonicalJson(value: unknown, limits?: object): string;
export function parseCanonicalJson(text: string, options?: object): unknown;
export function digestCanonical(domain: string, value: unknown, limits?: object): Promise<string>;
export function constantTimeEqual(left: string, right: string): boolean;
export function assertCanonicalText(value: unknown, label: string, options?: object): string;
export function assertSafeInteger(value: unknown, label: string, options?: object): number;
export function assertSha256(value: unknown, label: string, options?: object): string;
export function assertStableIdentifier(value: unknown, label: string, options?: object): string;

export const RUNTIME_STATUSES: readonly RuntimeStatus[];
export const OPERATION_ACTIONS: readonly OperationAction[];
export function projectRuntime(runtime: RuntimeProjection): RuntimeProjection;
export function digestRuntimeProjection(runtime: RuntimeProjection): Promise<string>;
export function buildOperationIntent(input: OperationIntent): OperationIntent;
export function digestOperationIntent(intent: OperationIntent): Promise<string>;
export function projectRuntimeFromLocalCanonicalJson(text: string): RuntimeProjection;
export function buildLocalOperationProposalFromCanonicalJson(text: string): OperationIntent;

export const UI_CONTROL_PROTOCOL_VERSION: string;
export const UI_CONTROL_PERMISSIONS: Readonly<Record<"READ" | "REQUEST" | "START" | "STOP", string>>;
export class RuntimeClient {
  constructor(options: {
    transport: UiControlTransport;
    maxPending?: number;
    clock?: () => number;
    protocolVersion?: string;
  });
  readonly connected: boolean;
  connect(manifest: object, options?: { signal?: AbortSignal }): Promise<RuntimeClientView>;
  refreshSession(options?: { signal?: AbortSignal }): Promise<RuntimeClientView>;
  revokeSession(options?: { signal?: AbortSignal }): Promise<void>;
  refreshView(options?: { signal?: AbortSignal }): Promise<RuntimeClientView>;
  applySnapshot(snapshot: object): Promise<RuntimeClientView>;
  readView(): RuntimeClientView;
  submitRequest(input: OperationInput): Promise<OperationView>;
  requestStart(input: OperationInput): Promise<OperationView>;
  requestStop(input: OperationInput): Promise<OperationView>;
  recoverOperation(operationId: string, options?: { signal?: AbortSignal }): Promise<OperationView>;
  recoverPending(options?: { signal?: AbortSignal; limit?: number }): Promise<readonly OperationView[]>;
  reconcile(observation: object): OperationView;
  exportRecoveryState(): object;
  restoreRecoveryState(state: object): RuntimeClientView;
  close(options?: { signal?: AbortSignal }): Promise<object>;
}

export class SameOriginHttpTransport implements UiControlTransport {
  constructor(options?: object);
  connect(manifest: object, options?: object): Promise<object>;
  readSnapshot(input: object, options?: object): Promise<object>;
  request(method: string, input: object, options?: object): Promise<object>;
  lookup(input: object, options?: object): Promise<object>;
  refresh(session: object, options?: object): Promise<object>;
  revoke(session: object, options?: object): Promise<void>;
  close(session: object, options?: object): Promise<void>;
}

export class SessionProvider {
  constructor(options: object);
  subscribe(listener: (event: object) => void): () => void;
  start(options?: object): Promise<RuntimeClientView>;
  refresh(options?: object): Promise<RuntimeClientView>;
  revoke(options?: object): Promise<void>;
  stop(): void;
}

export function normalizeSnapshot(snapshot: object, session: object): Promise<RuntimeSnapshot>;
export function validateSnapshotTransition(
  previous: RuntimeSnapshot | null,
  next: RuntimeSnapshot,
): RuntimeSnapshot;

export function createControlConsole(options: object): Readonly<{
  start(options?: object): Promise<void>;
  render(): void;
  destroy(): Promise<void>;
}>;

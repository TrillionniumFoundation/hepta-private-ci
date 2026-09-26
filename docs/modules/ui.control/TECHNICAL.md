# ui.control technical development guide

> Generated from `qualification/ui-control/UI_CONTROL_MANIFEST.json`. Edit the manifest or generator, not this file.

## 1. Scope and current truth

`ui.control` is an authority-free runtime-control client and browser console. It owns presentation state, authenticated session metadata, bounded local recovery records, and user interaction. Runtime owners retain authorization, durable operation identity, mutation authority, and terminal facts.

The active convergence branch is `work/ui-control-full-convergence-20260926`. The repository baseline used to start this convergence is `7cba86aff6e6d035ce0355d72d08896248cb04a5` / tree `7718bf09154a845a82b4b04d8a3c7fda15757b13`. Tracked documentation never self-certifies its own final commit; exact-head identity and outcomes are emitted by CI in `hepta.ui-control.qualification-receipt.v1`.

| Dimension | Current state |
|---|---|
| `clientCore` | `substantially_implemented` |
| `browserComposition` | `repository_shell_implemented` |
| `authentication` | `same_origin_session_adapter_implemented_deployment_unbound` |
| `transport` | `same_origin_http_adapter_implemented_deployment_unbound` |
| `serverIdempotency` | `contract_defined_backend_enforcement_unobserved` |
| `exactHeadQualification` | `required_and_derived_by_ci_not_committed` |
| `independentAcceptance` | `absent` |
| `releaseAuthorization` | `absent` |

## 2. Repository layout

- `apps/hepta-control-ui/src/`: framework-free ESM client core, HTTP transport, session provider, and browser controller.
- `apps/hepta-control-ui/web/`: semantic HTML/CSS browser shell.
- `apps/hepta-control-ui/test/`: unit, hostile-input, concurrency, recovery, package, and transport tests.
- `apps/hepta-control-ui/e2e/`: Chromium, Firefox, and WebKit product-path tests with axe-core.
- `docs/modules/ui.control/THREAT_MODEL.md`: trust boundaries and mitigations.
- `docs/modules/ui.control/SERVER_IDEMPOTENCY.md`: normative backend operation ledger contract.
- `docs/modules/ui.control/OPERATIONS.md`: deployment, monitoring, incident, and rollback runbook.

## 3. Public boundaries

- `RuntimeClient`
- `SameOriginHttpTransport`
- `SessionProvider`
- `createControlConsole`
- `projectRuntime`
- `buildOperationIntent`
- `digestOperationIntent`
- `normalizeSnapshot`
- `validateSnapshotTransition`
- `UiControlError`

The package exposes explicit `exports` for the root/core, browser controller, and HTTP transport. Imports under `@hepta/control-ui/src/*` are deliberately blocked. The browser build uses the same source modules as Node tests and does not need a framework runtime or unsafe HTML injection.

## 4. State model

A usable view is a tuple:

`(sessionId, connectionGeneration, runtimeGeneration, revision, semanticDigest, modules)`

The transition validator enforces:

1. The browser is never the runtime authority and never declares success from a local acknowledgement.
1. Every mutation binds session, connection generation, runtime generation, displayed revision, snapshot digest, operation id, semantic digest, target, action, and reason.
1. An operation id is reserved before the first await that can dispatch transport work.
1. Concurrent duplicate submissions share one in-flight promise; conflicting semantics fail closed.
1. Accepted-but-timeout is indeterminate and must be recovered by operation id before retry.
1. The backend operation-id unique constraint is the final idempotency authority.
1. Same generation and revision with a different semantic digest is snapshot drift and is rejected.
1. Control actions are disabled while the displayed view is stale or the session lacks the required permission.

The browser persists only bounded recovery metadata. It never persists credentials, CSRF tokens, backend responses containing secrets, or a claim that a mutation succeeded.

## 5. Mutation sequence

```mermaid
sequenceDiagram
  participant O as Operator
  participant UI as Browser shell
  participant C as RuntimeClient
  participant T as Same-origin transport
  participant L as Server operation ledger
  participant R as Runtime owner
  O->>UI: confirm action, target, reason
  UI->>C: submit operation intent
  C->>C: validate session/view and reserve operationId
  C->>T: one mutation request
  T->>L: INSERT operationId + semanticDigest (unique)
  alt new identity
    L->>R: enqueue authority-owned request
  else same identity and digest
    L-->>T: return existing record
  else same identity, different digest
    L-->>T: reject conflict
  end
  T-->>C: accepted acknowledgement or connection loss
  alt acknowledgement received
    C-->>UI: pending + auditTraceId
  else outcome ambiguous
    C-->>UI: indeterminate; require lookup
    UI->>T: lookup operationId + semanticDigest
    T->>L: read durable operation record
    L-->>UI: pending or terminal observation
  end
```

## 6. Digest and identity domains

| Value | Domain / authority | Purpose |
|---|---|---|
| Runtime projection digest | `hepta.ui-control.runtime-projection.v1` | Stable projection comparison |
| Snapshot digest | `hepta.ui-control.runtime-snapshot.v1` | Bind session/generation/revision/module bytes |
| Operation intent digest | `hepta.ui-control.operation-intent.v1` | Bind action/target/generation/revision/reason |
| Operation ID | Client-generated stable identifier; server unique index | Retry and audit identity |
| Audit trace ID | Server-generated | Cross-service observation and incident correlation |

Canonicalization accepts only bounded plain JSON values, safe integers, NFC strings without control/bidi-invisible characters, and keys other than `__proto__`, `constructor`, and `prototype`.

## 7. Authentication, permissions, and transport

The client requires an authenticated session with an exact protocol version, expiry, permission revision, connection generation, stable identity, and explicit permissions. Session refresh may increase permission revision or connection generation; a changed connection generation invalidates the displayed snapshot. Revocation and expiry disable control operations.

`SameOriginHttpTransport` enforces same-origin API paths, credentials-included requests, no-store caching, redirect rejection, bounded JSON responses, request IDs, CSRF on mutations, timeout/abort typing, and no automatic mutation retries. A network error after dispatch is ambiguous, not failed.

## 8. Browser interaction and accessibility

The browser shell provides:

- visible stale, disconnected, pending, terminal, failure, and indeterminate states;
- operation ID, runtime generation, revision, semantic digest binding, and audit trace display;
- modal confirmation for start, reconcile, and stop requests;
- duplicate-activation suppression before network dispatch;
- semantic tables, labels, alerts, live regions, skip navigation, visible focus, reduced-motion support, and focus restoration;
- axe-core scans and keyboard assertions in real Chromium, Firefox, and WebKit engines.

Automated checks do not replace manual screen-reader/operator acceptance; that remains an external signed gate.

## 9. Typed failures

Stable error codes include `UI_CONTROL_SESSION_EXPIRED`, `UI_CONTROL_PERMISSION_DENIED`, `UI_CONTROL_STALE_GENERATION`, `UI_CONTROL_STALE_REVISION`, `UI_CONTROL_SNAPSHOT_DRIFT`, `UI_CONTROL_PENDING_LIMIT`, `UI_CONTROL_OPERATION_CONFLICT`, `UI_CONTROL_BACKEND_REJECTED`, `UI_CONTROL_ACK_MISMATCH`, and `UI_CONTROL_AMBIGUOUS_SUBMISSION`.

Callers branch on `code` and `retryable`; parsing message text is unsupported.

## 10. Qualification

Repository checks:

- `npm run lint --prefix apps/hepta-control-ui`
- `npm test --prefix apps/hepta-control-ui`
- `npm run test:contract --prefix apps/hepta-control-ui`
- `npm run build --prefix apps/hepta-control-ui`
- `npm run test:e2e --prefix apps/hepta-control-ui`
- `node scripts/ui-control-artifacts.mjs --check`
- `python3 scripts/hepta-lane-b-path-guard.py self-test`
- `python3 -m unittest scripts/test_hepta_lane_b_path_guard.py`
- `python3 scripts/hepta-lane-b-path-guard.py verify`

The dedicated workflow binds checkout SHA and tree, runs unit/contract/build/browser/axe/Lane-B/document checks, verifies a clean tracked tree, and uploads the generated receipt and browser build manifest. A passing mock/protocol-equivalent E2E proves repository composition, not a production deployment.

## 11. Remaining external evidence gates

- production identity-provider and permission-revision integration
- deployed backend operation-id uniqueness and durable lookup evidence
- deployed CSP/CSRF/TLS/reverse-proxy observation
- production monitoring, alert routing, and rollback exercise
- independent assistive-technology and operator acceptance signature

## 12. Definition of done

The repository portion is complete when the authoritative branch is merged, generated projections are current, exact-head and synthetic-merge checks pass, all three browser engines and axe pass, Lane B truth passes, and a receipt is uploaded. Production completion additionally requires every external gate above and an independent acceptance signature.

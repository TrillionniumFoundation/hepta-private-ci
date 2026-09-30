# ui.control technical development guide

> Generated from `qualification/ui-control/UI_CONTROL_MANIFEST.json`. Edit the manifest or generator, not this file.

## 1. Scope and current truth

`ui.control` is an authority-free runtime-control client and browser console. It owns presentation state, authenticated session metadata, bounded local recovery records, and user interaction. Runtime owners retain authorization, durable operation identity, mutation authority, and terminal facts.

The active convergence branch is `work/ui-control-authoritative-closure-20260927`. The repository baseline used to start this convergence is `a126987b84737dbc2ee2592442a314117bddb4a2` / tree `a22fd0074c45ae6f3cef2092cd6e273bf9c26c30`. Tracked documentation never self-certifies its own final commit; exact-head identity and outcomes are emitted by CI in `hepta.ui-control.qualification-receipt.v2`.

| Dimension | Current state |
|---|---|
| `clientCore` | `substantially_implemented` |
| `browserComposition` | `repository_shell_implemented` |
| `browserCorrelationPrivacy` | `identifiers_redacted_in_dom_exact_in_client_state` |
| `dependencyLock` | `exact_npm_lock_committed_qualification_pending` |
| `sessionLifecycle` | `identity_permission_revision_and_shutdown_fenced` |
| `terminalEvidence` | `authenticated_backend_observation_projection_implemented` |
| `localRecovery` | `crash_consistent_scoped_directory_fail_closed_without_authority_claim` |
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
1. Session identity cannot change during refresh; permission revision cannot regress or conceal permission drift.
1. Revoke, close, and stopped refresh paths remove local control authority even when transport cleanup fails.
1. Local recovery storage failure is visible but cannot wedge or authorize a control request.
1. Session, operation, audit-trace, snapshot, semantic, and outcome correlation identifiers are rendered only in deterministic redacted form; full values remain outside DOM text and attributes.
1. Control actions are disabled while the displayed view is stale or the session lacks the required permission.
1. Snapshot refresh failure marks the view stale; view inspection removes expired session permissions without erasing pending operations.
1. Backend observations preserve the admission audit identity; missing or changed traces never authorize terminal cleanup.
1. An absent V1 lookup remains indeterminate because delayed admission is still possible; final non-admission requires a separately versioned durable backend fence.
1. Recovery import validates bounded data without executing accessors or inherited iterators, preserves live dispatch promises and terminal history, rejects conflicts atomically, and bounds the combined pending inventory.
1. Independent accessibility and security reviewers are distinct from one another and from deployment, release, and security approval authorities.
1. Production approval cannot predate deployment, real-backend, independent review, or operational evidence; accepted bundles expose only domain-separated principal digests.

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
- full runtime generation and revision display plus deterministic redaction of session, operation, audit-trace, snapshot, semantic, and outcome correlation identifiers; exact full identifiers remain in typed client state and transport objects and are not copied into DOM text or attributes;
- modal confirmation for start, reconcile, and stop requests;
- duplicate-activation suppression before network dispatch;
- semantic tables, labels, alerts, live regions, skip navigation, visible focus, reduced-motion support, and focus restoration;
- axe-core scans and keyboard assertions in real Chromium, Firefox, and WebKit engines.

Automated checks do not replace manual screen-reader/operator acceptance; that remains an external signed gate.

## 9. Typed failures

Stable error codes include `UI_CONTROL_SESSION_EXPIRED`, `UI_CONTROL_PERMISSION_DENIED`, `UI_CONTROL_STALE_GENERATION`, `UI_CONTROL_STALE_REVISION`, `UI_CONTROL_SNAPSHOT_DRIFT`, `UI_CONTROL_PENDING_LIMIT`, `UI_CONTROL_OPERATION_CONFLICT`, `UI_CONTROL_BACKEND_REJECTED`, `UI_CONTROL_ACK_MISMATCH`, and `UI_CONTROL_AMBIGUOUS_SUBMISSION`.

Callers branch on `code` and `retryable`; parsing message text is unsupported. Unknown exception messages are replaced by an operator-safe generic error before DOM rendering.

## 10. Evidence semantics

- **Observed outcome:** A concrete check ran and emitted a pass or failure observation for one exact subject. A later failure does not erase an earlier observation.
- **Accepted evidence:** A receipt was validated against its exact candidate, tree, deployment, and authority rules. Accepted stage evidence is monotone within an evidence bundle.
- **Overall acceptance:** The bundle is accepted only when every required stage, five distinct assurance principals, evidence-before-approval chronology, and the final production approval are accepted. A failed bundle may retain earlier accepted stage evidence without authorizing production or release.

Receipt schemas are sourced from the same manifest:

- `repositoryReceipts`: `hepta.ui-control.qualification-receipt.v2`
- `realBackend`: `hepta.ui-control.real-backend-receipt.v2`
- `deploymentSecurity`: `hepta.ui-control.deployment-security-receipt.v2`
- `independentAcceptance`: `hepta.ui-control.independent-acceptance-receipt.v2`
- `independentSecurity`: `hepta.ui-control.independent-security-review-receipt.v1`
- `operationalExercise`: `hepta.ui-control.operational-exercise-receipt.v1`
- `productionApproval`: `hepta.ui-control.production-approval-receipt.v1`
- `assuranceChain`: `hepta.ui-control.assurance-chain.v1`
- `externalEvidenceBundle`: `hepta.ui-control.external-evidence-bundle.v1`

## 11. Qualification

Repository checks:

- `npm ci --prefix apps/hepta-control-ui --ignore-scripts --no-audit --no-fund`
- `npm run lint --prefix apps/hepta-control-ui`
- `npm test --prefix apps/hepta-control-ui`
- `npm run test:contract --prefix apps/hepta-control-ui`
- `npm run build --prefix apps/hepta-control-ui`
- `npm run test:e2e --prefix apps/hepta-control-ui`
- `node scripts/ui-control-artifacts.mjs --check`
- `node scripts/ui-control-truth.mjs`
- `python3 scripts/hepta-lane-b-path-guard.py self-test`
- `python3 -m unittest scripts/test_hepta_lane_b_path_guard.py`
- `python3 scripts/hepta-lane-b-path-guard.py verify`

The dedicated workflow binds checkout SHA and tree, runs unit/contract/build/browser/axe/Lane-B/document checks, verifies a clean tracked tree, and uploads the generated receipt and browser build manifest. A passing mock/protocol-equivalent E2E proves repository composition, not a production deployment.

## 12. Remaining external evidence gates

- production identity-provider and permission-revision integration
- deployed backend operation-id uniqueness and durable lookup evidence
- deployed CSP/CSRF/TLS/reverse-proxy observation
- production monitoring, alert routing, and rollback exercise
- independent assistive-technology and operator acceptance signature
- five-principal review/approval separation and evidence-before-approval chronology

## 13. Definition of done

The repository portion is complete when the authoritative branch is merged, generated projections are current, exact-head and synthetic-merge checks pass, all three browser engines and axe pass, Lane B truth passes, and a receipt is uploaded. Production completion additionally requires every external gate above and an independent acceptance signature.

# ui.control technical development guide

> Generated from `qualification/ui-control/UI_CONTROL_MANIFEST.json`. Edit the manifest or generator, not this file.

**Source status:** `existing_bound`

**Bootstrap work package:** `UI-V5`

These registry facts identify present, bound source. They do not establish host execution, production composition or independent acceptance.

## 1. Scope and current truth

`ui.control` is an authority-free shared chat presentation core and secondary runtime Console. Conversations, message timeline and composer are the primary product interaction; both hosts follow apps/hepta-control-ui/CHAT_DESIGN.md. It owns presentation state, authenticated session metadata, bounded local recovery records, and user interaction. Runtime owners retain authorization, durable operation identity, mutation authority, and terminal facts.

The active convergence branch is `work/ui-chat-convergence-20261002`. The repository baseline used to start this convergence is `a126987b84737dbc2ee2592442a314117bddb4a2` / tree `a22fd0074c45ae6f3cef2092cd6e273bf9c26c30`. Tracked documentation never self-certifies its own final commit; exact-head identity and outcomes are emitted by CI in `hepta.ui-control.qualification-receipt.v2`.

| Dimension | Current state |
|---|---|
| `clientCore` | `rust_controller_with_legacy_node_reference_api` |
| `browserComposition` | `robrix_derived_makepad_shared_native_wasm_candidate_runtime_unqualified` |
| `browserCorrelationPrivacy` | `shared_presentation_fencing_implemented_canvas_host_acceptance_pending` |
| `dependencyLock` | `pinned_makepad_git_and_explicit_platform_patch_nightly_identity` |
| `sessionLifecycle` | `identity_permission_revision_and_shutdown_fenced` |
| `terminalEvidence` | `authenticated_backend_observation_projection_implemented` |
| `localRecovery` | `crash_consistent_scoped_directory_fail_closed_without_authority_claim` |
| `authentication` | `same_origin_session_adapter_implemented_deployment_unbound` |
| `transport` | `same_origin_http_adapter_implemented_deployment_unbound` |
| `serverIdempotency` | `contract_defined_backend_enforcement_unobserved` |
| `exactHeadQualification` | `required_and_derived_by_ci_not_committed` |
| `independentAcceptance` | `absent` |
| `releaseAuthorization` | `absent` |
| `chatPresentation` | `actual_robrix_source_derivatives_shared_makepad_widgets` |
| `chatOwnerComposition` | `external_human_session_signer_and_browser_bridge_prerequisites_unqualified` |
| `consoleComposition` | `operational_widgets_not_yet_ported_to_makepad` |
| `legacyHosts` | `egui_and_semantic_dom_superseded_compatibility_only` |

## 2. Repository layout

- `apps/hepta-control-ui/rust/`: existing Rust controller/owner projections and canonical Robrix-derived Makepad shared native/Web host; operational Console composition remains pending.
- `apps/hepta-control-ui/src/`: historical Node differential-reference APIs, excluded from default product exports and the browser artifact.
- `apps/hepta-control-ui/web/`: superseded semantic-DOM compatibility shell, not the normal product entrypoint.
- `apps/hepta-control-ui/test/`: unit, hostile-input, concurrency, recovery, package, and transport tests.
- `apps/hepta-control-ui/e2e/`: legacy semantic-DOM tests plus new actual Makepad host startup/capture checks; canvas accessibility and full interaction acceptance remain required.
- `docs/modules/ui.control/THREAT_MODEL.md`: trust boundaries and mitigations.
- `docs/modules/ui.control/SERVER_IDEMPOTENCY.md`: normative backend operation ledger contract.
- `docs/modules/ui.control/OPERATIONS.md`: deployment, monitoring, incident, and rollback runbook.

Declared roots not yet present:

None.

## 3. Public boundaries

- `rust/core: authority-free control, chat, owner and timeline contracts`
- `rust/robrix-ui: shared Robrix-derived native/WASM widgets`
- `Rust Makepad application plus generated platform/ABI glue; no JavaScript application exports`

The default package has an empty JavaScript export map and ships only the Robrix-derived Rust/Makepad artifact. Historical Node contracts are quarantined differential oracles under src/ORACLE.json, not application entrypoints. Build/dev/start/desktop commands use Makepad. Framework JavaScript is generated platform/ABI glue; application layout and events are Rust.

The following control-state and mutation contracts describe retained owner adapters. They are not a claim that operational Console controls or a production authenticated chat bridge are composed into the new host.

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
1. Retained in-memory operations, completed history, exports and lookups are scoped to the authenticated identity; switching identities preserves original records and does not bypass the total pending capacity.
1. HTTP request bodies are validated bounded canonical JSON of at most 64 KiB; pre-dispatch failures declare requestDispatched=false, and rejected response bodies are cancelled.
1. Local recovery storage failure is visible but cannot wedge or authorize a control request.
1. Session, operation, audit-trace, snapshot, semantic, and outcome correlation identifiers are rendered only in deterministic redacted form; full values remain outside DOM text and attributes.
1. Control actions are disabled while the displayed view is stale or the session lacks the required permission.
1. Snapshot refresh failure marks the view stale; view inspection removes expired session permissions without erasing pending operations.
1. Raw backend session and acknowledgement data are validated before cleanup decisions; operation intent values are captured before asynchronous hashing.
1. Backend observations preserve the admission audit identity; missing or changed traces never authorize terminal cleanup.
1. An absent V1 lookup remains indeterminate because delayed admission is still possible; final non-admission requires a separately versioned durable backend fence.
1. Recovery import validates bounded data without executing accessors or inherited iterators, preserves live dispatch promises and terminal history, rejects conflicts atomically, and bounds the combined pending inventory.
1. Independent accessibility and security reviewers are distinct from one another and from deployment, release, and security approval authorities.
1. Production approval cannot predate deployment, real-backend, independent review, or operational evidence; accepted bundles expose only domain-separated principal digests.
1. Browser failures render only known error codes with fixed operator messages; untrusted validation labels, detailed messages and causes remain outside DOM text and live regions, and startup diagnostics emit only known error codes.
1. Console replacement resets interaction state; destroyed controllers cannot alter replacement controls, and every destroy caller waits for the same cleanup settlement.

The retained control adapter persists only bounded recovery metadata, never credentials or success claims. The new Makepad chat workspace currently keeps local drafts transiently and does not claim reload recovery or a configured live chat transport.

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

`SameOriginHttpTransport` enforces same-origin API paths, credentials-included requests, no-store caching, redirect rejection, 64 KiB canonical JSON requests, one-megabyte JSON responses, explicit pre-dispatch failure classification, request IDs, CSRF on mutations, timeout/abort typing, and no automatic mutation retries. A network error after dispatch is ambiguous, not failed.

## 8. Browser interaction and accessibility

The retained legacy semantic-DOM shell provides the following interaction and
test surfaces. They do not describe or qualify the new Makepad canvas host:

- visible stale, disconnected, pending, terminal, failure, and indeterminate states;
- full runtime generation and revision display plus deterministic redaction of session, operation, audit-trace, snapshot, semantic, and outcome correlation identifiers; exact full identifiers remain in typed client state and transport objects and are not copied into DOM text or attributes;
- modal confirmation for start, reconcile, and stop requests;
- duplicate-activation suppression before network dispatch;
- semantic tables, labels, alerts, live regions, skip navigation, visible focus, reduced-motion support, and focus restoration;
- axe-core scans and keyboard assertions in real Chromium, Firefox, and WebKit engines.

Makepad keyboard, IME and accessibility behavior still require host-specific
verification. Legacy automated checks do not replace manual screen-reader/operator
acceptance; that remains an external signed gate.

### Shared Rust preedit routing candidate

The canonical dispatcher is `apps/hepta-control-ui/rust/robrix-ui/src/app.rs`.
`ime_router.rs` resolves the real composing search/composer field and current
presentation epoch before application widget dispatch. `ime_pointer_gate.rs`
retains bounded rejected gesture identities through release, independently of
room/account changes. A cloned filtered touch packet returns each forwarded
contact's real handled/sweep claims to the original event; platform processing
still receives the original packet and owns capture cleanup.

Raw focus-changing or editing key paths must not reinterpret active IME candidate
controls as application commands. Real platform `TextInput` commit/cancel state
continues through the existing typed input boundary. Responsive layout selection
is held during preedit and re-evaluated on its completion. These are source
mechanisms; their completeness must be tested against actual SDK event ordering,
not a boolean-state model alone. In-field pointer edits, clipboard cut, detached
owners and exhaustion/recovery remain mandatory adversarial cases.

The standalone pointer-policy tests are distinct from a real Makepad TextInput
probe and from actual OS/browser IME. Retained DOM/egui tests qualify neither the
new router nor the canvas accessibility tree. Follow the source README for exact
stable/nightly build commands and preserve all production owner/signing gates.

## 9. Typed failures

Stable error codes include `UI_CONTROL_SESSION_EXPIRED`, `UI_CONTROL_PERMISSION_DENIED`, `UI_CONTROL_STALE_GENERATION`, `UI_CONTROL_STALE_REVISION`, `UI_CONTROL_SNAPSHOT_DRIFT`, `UI_CONTROL_PENDING_LIMIT`, `UI_CONTROL_OPERATION_CONFLICT`, `UI_CONTROL_BACKEND_REJECTED`, `UI_CONTROL_ACK_MISMATCH`, and `UI_CONTROL_AMBIGUOUS_SUBMISSION`.

Callers branch on `code` and `retryable`; parsing message text is unsupported. The console renders only known error codes with fixed operator messages. Detailed messages, backend validation labels, details and causes remain outside DOM text and live regions.

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
- `npm run legacy:test-contract --prefix apps/hepta-control-ui`
- `npm run build --prefix apps/hepta-control-ui`
- `npm run test:e2e --prefix apps/hepta-control-ui`
- `node scripts/ui-control-artifacts.mjs --check`
- `python3 scripts/ui-control-source-map.py`
- `python3 scripts/hepta-lane-b-path-guard.py self-test`
- `python3 scripts/hepta-lane-b-path-guard.py verify`

The dedicated workflow retains explicit legacy controller/DOM parity checks and separately builds the actual Makepad host. The new host job checks exact source, native presentation tests, WASM, strict-CSP/static ABI packaging and actual browser startup/screenshots. Startup smoke does not establish keyboard/IME/scroll, screen-reader, mobile input or visual acceptance. Old DOM axe results do not qualify a canvas host; deployment requires independent evidence.

## 12. Remaining external evidence gates

- production identity-provider and permission-revision integration
- deployed backend operation-id uniqueness and durable lookup evidence
- deployed CSP/CSRF/TLS/reverse-proxy observation
- production monitoring, alert routing, and rollback exercise
- independent assistive-technology and operator acceptance signature
- five-principal review/approval separation and evidence-before-approval chronology

## 13. Definition of done

The new UI remains incomplete until actual Robrix host interactions, responsive scroll/draft preservation, real CJK IME, accessibility, visual quality and Console composition pass on the target hosts. Compilation, bridge extraction and historical controller receipts are insufficient. Production completion also requires qualified owner/signer/bridge integration, platform packaging, all external gates and independent acceptance; no merge or release authorization is implied.

## 16. V8.2 pre-coding implementation-readiness overlay

Use the [parallel development plan](../../readiness/PARALLEL_DEVELOPMENT.md) and
[module execution dossier](../../../qualification/module-execution-dossiers/MODULE_DOSSIERS.json)
for lane ownership, execution-receipt fields and external evidence requirements.
These are specification and navigation references. They do not qualify the new
Makepad host, close the remaining integration gates or grant release authority.

## 17. Source implementation receipt

This section records the source-location obligation of `UI-V5`, not an execution or acceptance receipt. The registered source roots are:

- `apps/hepta-control-ui`

The Rust controller and Robrix-derived Makepad widgets are present in that source tree. [IMPLEMENTATION_MAP.json](IMPLEMENTATION_MAP.json) binds the mapped paths and exact source objects; its source observation must be checked against the candidate by `python3 scripts/ui-control-source-map.py`.

The current chat host has no qualified production principal/signer/bridge, operational Console composition remains pending, and transient chat drafts do not imply durable reload recovery. Actual execution outcomes belong only to source-bound external CI receipts. This source-location record grants no runtime authority, production-writer authority, independent acceptance, merge or release authorization.

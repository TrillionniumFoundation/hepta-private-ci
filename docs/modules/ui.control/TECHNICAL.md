# ui.control technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `ui.control`

**Owner:** `ui-platform`

**Deputy:** `accessibility`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `UI-V5`

This stable document is the implementation guide for `ui.control`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. The implementation-facing request/transport schemas, local commands, state-machine details and deployment checklist live in [`DEVELOPMENT.md`](DEVELOPMENT.md). Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Present runtime state and requests without issuing authority or directly writing stores.

The primary owner `ui-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `accessibility` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `presentation`, kind `web`, state model `stateless` and architecture role `presentation` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `apps/hepta-control-ui`

Existing declared roots at this exact source snapshot:

- `apps/hepta-control-ui`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact. The declared roots above are materialized in the bounded V8 source candidate and are covered by the dedicated closed-world inventory, focused tests, all-target compilation, strict lint and exact-head qualification. This status does not activate `ui.control`, create a production caller, grant runtime or effect authority, issue independent acceptance, select or promote a candidate, or authorize release. Any later source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide in one candidate.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `runtime.agentd`

Authoritative write domains:

None.

Explicitly denied capabilities:

- `authority_issuance`
- `direct_store_write`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `canonical protocol and resource guard`
- `state projection`
- `authenticated runtime client`
- `browser interaction controller`
- `accessibility and error recovery`

`src/protocol.js` owns bounded canonical values, stable typed errors and semantic SHA-256 binding. `src/control.js` owns the authority-free display projection and UI operation proposal. `src/runtime-client.js` owns authenticated session-local state, coherent snapshots, pending operation identities and reconciliation. `src/pending-store.js` provides a bounded non-authoritative durable mirror of unresolved identities. `src/http-transport.js` and `src/browser-host.js` provide the repository-owned same-origin HTTPS/CSRF transport/bootstrap boundary. `src/browser-app.js` and `src/web-main.js` provide the framework-free browser shell and deployable source composition.

Ingress validates identity, version, size, scope and revision before domain logic. Backend module observations are projected through an explicit display allowlist before `readView()`; provider-specific payloads or secret-bearing fields never become browser view fields merely because the backend supplied them. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

None.

Consumed contracts:

- `DomainRead::runtime_health_observationV1`
- `ModulePort::runtime.agentd::ui.control`

Critical protocol schemas:

None.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

`UiOperationProposalV1` is a UI-local, authority-free proposal and is not `kernel.operations`' `OperationIntentV1`. The historical JavaScript export named `buildOperationIntent` is only a compatibility alias for the UI proposal builder; a separately authorized backend adapter remains responsible for constructing/admitting any canonical effect-bearing operation contract.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

None.

Read-only data dependencies:

- `runtime_health_observation`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/ui.control.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/ui.control.md).

The client keeps at most the current and immediately previous coherent runtime snapshots in memory and at most 1024 unresolved operation identities. When a `pendingStore` is configured, only bounded identity/provenance/reconciliation metadata is durably mirrored; proposal/scope payloads are excluded. An operation is inserted and durably mirrored before transport I/O, so persistence failure prevents dispatch. Identical operation identity plus identical canonical semantics is idempotent locally; the same identity with changed semantics fails closed.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

The runtime/client boundary exposes stable typed error codes for invalid input, unauthenticated sessions, incompatible protocol versions, stale snapshots, request rejection, backend unavailability, protocol violations, reconciliation mismatch, capacity exhaustion and oversized projected views.

A transport exception after submission does not erase the local operation and does not imply backend cancellation. The operation becomes `indeterminate`. Reconnect preserves the operation ID, semantic digest and immutable origin provenance and calls the reconciliation boundary; it does not blindly re-submit the mutation. In-flight acknowledgements are checked against that captured provenance even if close/reconnect changes the current session while the request is awaiting I/O. Reconciliation is dispatched in bounded batches of at most 8 concurrent read-only queries, backs off from 1 s to 60 s and stops automatic attempts after 64 failures/absences or 24 h, marking `recoveryRequired` for explicit read-only operator reconciliation. Only a provenance-valid registered terminal status accompanied by `terminalObserved: true` removes pending work.

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/ui.control.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/ui.control.md). A source library or fixture cannot stand in for an unimplemented durable backend recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

The source client computes semantic SHA-256 from the final canonical proposal/scope instead of trusting a caller-supplied digest. Transport request and reconciliation envelopes are immutable at the JavaScript boundary. Stop scope is an explicit bounded record. The browser shell renders through DOM `textContent`, collapses duplicate logical actions, restores action focus after rerender and disables mutation from stale or externally blocked views. The concrete HTTP adapter is same-origin, HTTPS outside loopback, `credentials: same-origin`, `cache: no-store`, redirect-fail-closed and fresh-CSRF protected for POSTs.

Negative tests cover denied capabilities, stale views, replay with payload drift, unknown fields, oversize input, provenance mismatch, hostile local fixture objects, scope shape, secret/provider leakage and response-loss reconciliation. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/ui.control.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Current source-enforced ceilings are: projected runtime view <= 1 MiB UTF-8 JSON; canonical request/scope <= 64 KiB; canonical depth <= 32; canonical nodes <= 4096; modules per snapshot <= 4096; pending operations <= 1024; stable identifiers <= 128 characters. These are implementation limits, not selected-host performance measurements.

Current limits are implemented in [apps/hepta-control-ui/src/protocol.js](../../../apps/hepta-control-ui/src/protocol.js) and [apps/hepta-control-ui/src/runtime-client.js](../../../apps/hepta-control-ui/src/runtime-client.js). UI timing is not hardware-stop timing.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

JavaScript presentation/client boundary and static browser artifact, not a server or authority issuer. Connect an authenticated versioned backend, preserve request IDs over reconnect and visibly distinguish stale/pending/indeterminate/recovery-required states. The repository now emits a security-header policy and same-origin HTTPS/CSRF adapter, and the shell implements focus recovery plus duplicate-action blocking. The selected host must actually apply the headers/session policy, and real backend authority plus independent cross-browser/screen-reader acceptance remain external qualification gates.

Current operating and state-format references:

- [apps/hepta-control-ui/README.md](../../../apps/hepta-control-ui/README.md).
- [docs/modules/ui.control/DEVELOPMENT.md](DEVELOPMENT.md).
- [docs/modules/ui.control/IMPLEMENTATION_MAP.json](IMPLEMENTATION_MAP.json).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [apps/hepta-control-ui/test/control.test.js](../../../apps/hepta-control-ui/test/control.test.js) — display projection and authority-free proposal boundaries.
- [apps/hepta-control-ui/test/runtime-client.test.js](../../../apps/hepta-control-ui/test/runtime-client.test.js) — transport payload, semantic digest, response loss, reconnect, provenance, capacity and typed failure cases.
- [apps/hepta-control-ui/test/protocol-regression.test.js](../../../apps/hepta-control-ui/test/protocol-regression.test.js) — hostile fixture objects, exact byte/identifier boundaries, independent target/display revisions and explicit stop scope.
- [apps/hepta-control-ui/test/browser-app.test.js](../../../apps/hepta-control-ui/test/browser-app.test.js) — display-safe browser model, stale mutation blocking and final revision binding.
- [apps/hepta-control-ui/test/hardening.test.js](../../../apps/hepta-control-ui/test/hardening.test.js) — in-flight provenance races, durable pending identity, persistence fail-closed behavior, duplicate-action collapse, focus recovery and same-origin CSRF transport policy.
- `npm --prefix apps/hepta-control-ui run browser-e2e` — real-Chrome smoke over the generated static artifact and a bounded mock backend; this is source qualification, not independent deployment acceptance.

From the repository root, run:

```bash
npm --prefix apps/hepta-control-ui run check
npm --prefix apps/hepta-control-ui run build
```

The commands are test/build invocations, not stored pass receipts. Exact source and deterministic synthetic-merge execution are owned by `.github/workflows/hepta-ui-control.yml`; Lane-B source closure also invokes the package check/build when `apps/hepta-control-ui/**` or the module documentation changes. Inspect exact-candidate workflow output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/ui.control.md) separately labels external product/deployment acceptance work.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `UI-V5`

The bootstrap package is `UI-V5`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `ui.control`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `UI-V5`

- State: `source_implemented_execution_pending`; priority: `2`; parallel class: `independent_source_preparation`.
- Owner/deputy: `ui-platform` / `accessibility`.
- Allowed write paths:
- `apps/hepta-control-ui/**`
- `apps/hepta-native/**`
- Development predecessors:
- `DOC-1-V8-SEMANTIC-UPGRADE`
- Activation predecessors:
- `P0.8B-READINESS`
- Required deliverables:
- `exact_source_identity`
- `source_inventory`
- `static_verification`
- `focused_tests`
- `package_tests`
- `all_target_check`
- `strict_lint`
- `clean_worktree`
- `exact_head_execution`
- `merge_candidate_execution`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `ui.control` to primary lane `LANE-B-RUNTIME`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `ui.control` is implemented by work package `UI-V5` in:

- `apps/hepta-control-ui`

The control-ui package is checked and built at exact PR source and deterministic synthetic merge by `.github/workflows/hepta-ui-control.yml`; the dedicated workflow also exercises the built artifact in real Google Chrome. Lane-B source closure also runs its package check/build. `.github/workflows/hepta-consolidated-source.yml` remains a broader repository qualification workflow; it is not treated as the sole package-level execution receipt for `ui.control`. These receipts are source implementation evidence only. They grant no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.

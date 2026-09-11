# channel.matrix technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `channel.matrix`

**Owner:** `channels-platform`

**Deputy:** `security-authority`

**Lifecycle:** `existing`

**Source status:** `existing_bound`

**Bootstrap work package:** `MATRIX-1-CHANNEL-BOUNDARY`

This stable document is the implementation guide for `channel.matrix`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Translate Matrix ingress and governed sends without writing agent state or self-authorizing delivery.

The primary owner `channels-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `security-authority` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `adapter`, kind `daemon`, state model `stateful` and architecture role `checked_adapter` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-matrix-sdk`
- `codex-rs/hepta-matrixd`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-matrix-sdk`
- `codex-rs/hepta-matrixd`

Non-authoritative implementation evidence roots:

- `codex-rs/hepta-matrix-sdk`
- `codex-rs/hepta-matrixd`
- `codex-rs/hepta-matrix-store`
- `codex-rs/hepta-matrix-protocol`

Declared roots not yet present:

None.

`existing_bound` is a source-location fact. For a target or unbound module, development begins with `MATRIX-1-CHANNEL-BOUNDARY` and materializes the declared root before source completion. Aggregate evidence roots are read-only decomposition evidence; they transfer no ownership and cannot become a second permanent implementation. A source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide in one candidate.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `runtime.agentd`
- `kernel.authority`
- `kernel.operations`

Authoritative write domains:

- `matrix_ingress_projection`
- `matrix_dispatch_ledger`

Explicitly denied capabilities:

- `agent_store_write`
- `self_issued_send_authority`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `bootstrap and configuration loader`
- `supervision loop`
- `durable state projection`
- `readiness and shutdown controller`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::matrix_dispatch_ledgerV1`
- `DomainRead::matrix_ingress_projectionV1`

Consumed contracts:

- `DomainRead::authority_leaseV1`
- `DomainRead::capability_revocationV1`
- `DomainRead::cross_owner_outboxV1`
- `DomainRead::operation_ledgerV1`
- `DomainRead::runtime_health_observationV1`
- `ModulePort::kernel.authority::channel.matrix`
- `ModulePort::kernel.operations::channel.matrix`
- `ModulePort::runtime.agentd::channel.matrix`
- `OperationIntentV1`
- `VerifiedUseTokenWitnessV1`

Critical protocol schemas:

None.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `matrix_dispatch_ledger`
- `matrix_ingress_projection`

Read-only data dependencies:

- `authority_lease`
- `capability_revocation`
- `cross_owner_outbox`
- `operation_ledger`
- `runtime_health_observation`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

Central synchronous RPC on the local hot path is `false`. Bounded cached control input is `true`. A fallback is required: `true`.

Ingress enforces queue, payload, concurrency and deadline limits. Cancellation is observed at defined boundaries and cannot relabel a terminal state already being committed. Retries require a stable operation identity and equal semantic digest. Timeout at an external boundary becomes indeterminate absent verified terminal acknowledgement.

State transitions are monotonic within an attempt. A crash between authorization and terminal observation leaves pending or indeterminate state, never invented success. Reconciliation is fenced by authority epoch and predecessor identity. Concurrent writers use transactions or compare-and-swap; last-write-wins is forbidden for authoritative facts.

## 8. Failure semantics, recovery and rollback

Failures are classified as validation rejection, authority rejection, unavailable dependency, bounded timeout, storage failure, conflict, cancellation, indeterminate effect, integrity failure or internal invariant violation. Errors expose safe identifiers and digests, not raw secrets, provider payloads or untrusted content.

Startup validates configuration, schema and integrity, recovers incomplete local transactions, scans outbox state and gates readiness in that order. Integrity uncertainty, unknown schema or conflicting durable identity fails closed or quarantines. Optional context or advisory signals degrade only when fallback cannot widen authority.

Every state-changing package names a rollback predecessor and tests crash/reopen behavior. Rollback restores code, configuration and compatible state. External effects are never rolled back by assumption; they require acknowledgement, compensation or quarantine.

## 9. Security, privacy and threat controls

Owned threat entries:

- `matrix_self_issued_send`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

Implementing packages publish measurable latency, throughput, memory, storage growth, queue depth and recovery budgets. Bounds are enforced, not only observed. Backpressure rejects or sheds explicitly and never creates unbounded tasks or retries.

Hot paths avoid global locks, synchronous central control and full-store scans. Expensive verification uses bounded indexes, snapshots or staged slow paths. Caches bind revision and expiry and invalidate on revocation, correction, deletion or generation change. Benchmarks include steady state, cold start, maximum input, contention, degraded dependency and recovery.

## 11. Observability and operations

Structured events include module, operation or attempt identity, source revision, outcome class, duration, bounded resource use and safe digest references. Metrics include ingress, rejection, saturation, transaction conflicts, dependency latency, reconciliation backlog, integrity failures, fallback use and recovery duration.

Readiness means required dependencies, schema and integrity are verified; liveness only means progress is possible. Operator surfaces never expose raw secrets or unbounded payloads. Alerts cover sustained rejection, retry storms, aged pending/indeterminate state, integrity failure, capacity exhaustion, projection lag and rollback failure.

## 12. Verification and qualification

Minimum checks are exact source identity, source inventory, static verification, focused tests, package tests, all-target compilation, strict lint, clean worktree, exact-head execution and synthetic-merge execution. Stateful modules add migration, crash/reopen, corruption, idempotency, conflict and reconciliation. Adapters add revoked/stale grant, payload drift, timeout and indeterminate-outcome tests.

The implementing team cannot issue independent acceptance. Fixture success proves only the tested boundary at the exact candidate; it does not prove a production caller, physical effect, operator acceptance, promotion or release.

## 13. Implementation sequence and work packages

Applicable work packages:

- `MATRIX-1-CHANNEL-BOUNDARY`

The bootstrap package is `MATRIX-1-CHANNEL-BOUNDARY`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR carries one bounded envelope with contracts, domains, denied authorities, resources, rollback and stop conditions.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `channel.matrix`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `MATRIX-1-CHANNEL-BOUNDARY`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `channels-platform` / `security-authority`.
- Allowed write paths:
- `codex-rs/hepta-matrix-sdk/**`
- Development predecessors:
- `P0.7B-B3-BOUNDARIES`
- Activation predecessors:
- `P0.7B-B3-BOUNDARIES`
- Required deliverables:
- `exact_source_identity`
- `static_verification`
- `focused_tests`
- `clean_worktree`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `channel.matrix` to primary lane `LANE-B-RUNTIME`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Coding begins only with a current `CanonicalSourceReceiptV1`, a frozen contract/readiness digest, the existing bounded work-package envelope, defined mandatory fixtures, deterministic fallback and zero authority delta. This overlay closes documentation ambiguity only; it does not change source status, activation, acceptance, selection, promotion or release.
## 17. Lane B source inventory observation

The declared source roots for `channel.matrix` are present at the bound baseline:

- `codex-rs/hepta-matrix-sdk`
- `codex-rs/hepta-matrixd`

Exact paths and inspected symbols are recorded in `docs/lane-b/LANE_B_CLOSURE.json` and `qualification/module-execution-dossiers/NATIVE_BINDINGS.json`. The read-only gate `.github/workflows/hepta-lane-b-closure.yml` validates the exact source candidate, registered symbols, focused package tests and deterministic merge candidate. A source observation is not product execution, deployment qualification, independent acceptance, promotion or release evidence.

## 18. Lane B current capability, native mapping and remaining gates

<!-- generated: hepta-lane-b-closure -->

This section is generated from `docs/lane-b/LANE_B_CLOSURE.json` and is the current Lane B status projection. It separates source observation from product execution and supersedes any broader interpretation of a source-location receipt.

### Current source capability

The Matrix SDK source implements bounded ingress and durable-outbox transport, while the daemon source bridges one enrolled room to the existing Agentd and App Server session path.

### Target capability

A scoped Matrix channel with durable sync and send identities, redaction propagation, encrypted-session recovery, rate-limit handling and exact terminal delivery observations.

### Native source mapping

| Design operation | Source path and symbols | Mapping disposition |
|---|---|---|
| `ingest_and_dispatch_matrix_events` | `codex-rs/hepta-matrix-sdk/src/lib.rs` — `MatrixIngress`, `dispatch_outbox_once`, `MatrixSdkClient` | `exact_source_boundary` |
| `run_matrix_daemon_and_bridge_session` | `codex-rs/hepta-matrixd/src/lib.rs` — `run`, `MatrixRuntime`, `MatrixAppServerTransport` | `exact_source_boundary` |

### Remaining bridges

- Freeze Matrix specification, SDK and homeserver compatibility and document E2EE key lifecycle and recovery.
- Qualify sync-token, redaction, retry-after, poisoned-event and acknowledgement-loss behavior against a real homeserver.
- Publish daemon service, credential permissions, migration and rollback procedures.

### Evidence boundary

The mapping above proves named source locations and symbols at the bound baseline. Exact-head and deterministic-merge CI must still pass for each candidate. It grants no model, provider, tool, network, filesystem, Matrix, platform, deployment, acceptance, promotion or release authority.

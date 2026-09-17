# cognitive.read technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `cognitive.read`

**Owner:** `cognitive-platform`

**Deputy:** `agent-runtime`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `MEM-READ-1-SNAPSHOT-PORT`

This stable document is the implementation guide for `cognitive.read`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Expose snapshot-bound cognitive reads without write authority.

The primary owner `cognitive-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `agent-runtime` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `port`, state model `stateless` and architecture role `contract` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-cognitive-read`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-cognitive-read`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

Current repository state is deliberately split rather than collapsed into one production boolean:

- `implemented = true`: typed V1/V2 read semantics, the existing SQLite Lane C adapter and owner-side receipt finalization exist in source.
- `composed = true`: Agentd consumes the durable Lane C cut and the native infer worker calls Agentd cognitive context and finalization before model `TurnStart`.
- `qualified = false`: exact-candidate independent qualification, target-host acceptance, activation and release remain separate gates.

The machine-readable source of this split is [IMPLEMENTATION_MAP.json](IMPLEMENTATION_MAP.json). A composed map carries exact `sourceObjects` for its owner root, native operations and product callers. `scripts/hepta-implementation-maps.py verify` recomputes those Git tree/blob identities from the tested checkout; a relevant source change without a refreshed map is a hard stale-map failure. The shared `sourceBase` remains a compatibility baseline and is not used as a self-referential claim that the map contains the hash of the commit containing itself.

### Native source and scope

The registered primary source is [codex-rs/hepta-cognitive-read/src/v2.rs](../../../codex-rs/hepta-cognitive-read/src/v2.rs); observed identifiers include `ReadRequestV2`, `ReadResultV2`, `read_v2`, `binding_digest`. The durable adapter is [codex-rs/hepta-memory/src/lane_c_snapshot.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot.rs). The production owner consumer and exact receipt finalizer are [codex-rs/hepta-agentd/src/cognitive_context.rs](../../../codex-rs/hepta-agentd/src/cognitive_context.rs). The durable pre-effect journal transition is in [codex-rs/hepta-infer-core/src/native_control.rs](../../../codex-rs/hepta-infer-core/src/native_control.rs), and the final model-effect consumer is [codex-rs/hepta-infer-worker-host/src/native_app_server.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server.rs). Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/cognitive.read.md#8-current-native-implementation) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.read.md) for the implemented subset and remaining qualification work.

## 3. Boundary, responsibilities and non-goals

The SQLite owner exposes `CognitiveStore::lane_c_snapshot` and
`DurableCognitiveSnapshot::read(ReadRequestV2)` through `hepta-memory`. This is a
native read-through adapter to the existing durable store. It authorizes the
exact scope, preserves record and citation IDs, includes committed tombstones,
and admits only verified, currently valid live heads. Agentd compares retrieved
revision/content digests and calls `revalidate_lane_c_snapshot` before publishing
its cognitive-context response.

That response is still only an observed historical cut. For model execution the
infer worker retains `snapshot_digest` and `read_digest`. After establishing the
exact App Server thread and rechecking the Agent lifecycle generation, it first
syncs the exact thread/provider/context dispatch intent to the existing durable
native journal, then calls `AgentdClient::finalize_cognitive_context` immediately
before `TurnStart`. The owner reacquires the canonical Lane C cut, exact-compares
the snapshot digest, reproduces the same bounded V2 read receipt, exact-compares
the read digest, and revalidates the cut again. Any correction,
delete/tombstone, validity change, citation/frontier change or owner conflict
observed before finalization fails closed and the stale context is not sent to
the model. If finalization or cancellation fails after the synced dispatch intent
but before `TurnStart`, durable control records a proven pre-turn stop and
releases the local slot without fabricating provider terminality or token usage.
A successful finalization is still an observation, not a freshness/revocation
lease over writes that occur after it returns.

`AuthoritativeCognitiveSnapshotProvider`, `SnapshotAcquisitionRequestV1`,
`AuthoritativeReadResultV1` and `read_authoritative` remain source-compatible
exports for qualification/compatibility, but are explicitly deprecated as
production entrypoints. They are not a second supported or composed acquisition
path. Production authority semantics are the durable Lane C cut plus explicit
owner revalidation/finalization. The public `AuthoritativeSnapshotV1` envelope
remains available where Lane C qualification needs to bind an externally frozen
generation vector.

Snapshot generation alone does not detect validity expiry without a write. See
`codex-rs/hepta-memory/LANE_C_SQLITE.md`; neither the owner-local V2 encoding nor
the finalization protocol grants effects to read results.

Direct dependencies:

- `cognitive.types`

Authoritative write domains:

None.

Explicitly denied capabilities:

- `write_authority`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `snapshot acquisition`
- `scope and redaction filter`
- `cache boundary`
- `consistency verifier`
- `effect-boundary receipt finalizer`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `ModulePort::cognitive.read::compact.engine`
- `ModulePort::cognitive.read::context.compiler`
- `ModulePort::cognitive.read::memory.federation`
- `ModulePort::cognitive.read::memory.retrieval`
- `ModulePort::cognitive.read::neuron.runtime`
- `ModulePort::cognitive.read::objective.compiler`
- `ModulePort::cognitive.read::utility.ndu`

Consumed contracts:

- `ModulePort::cognitive.types::cognitive.read`

Critical protocol schemas:

None.

`ReadRequestV2`/`ReadResultV2` are owner-local crate-native deterministic encodings, not a cross-module `ModulePort`, durable record or registered wire schema. The Agentd `CognitiveContext` and `CognitiveContextFinalize` methods are the actual bounded local process boundary used by the native host; the finalize request carries the observed `snapshot_digest` and `read_digest` back to the owner for exact revalidation and does not convert those digests into bearer authority.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

None.

Read-only data dependencies:

- canonical owner `cognitive_1.sqlite3` through `hepta-memory` Lane C snapshot APIs

`cognitive.read` is never an authoritative writer. The canonical memory owner remains responsible for mutations, revision/generation fencing, lineage, correction, deletion and revocation. Read projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

The module introduces no independent database schema or migration. SQLite migration/open integrity remains owned by `hepta-memory`; the read adapter refuses corrupt or incompatible owner state rather than creating an alternate store.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/cognitive.read.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. One Lane C snapshot is read from one SQLite read transaction. Agentd revalidates that cut before response publication. For model execution the native worker syncs its dispatch intent, then invokes owner finalization again before `TurnStart`; a proven local stop before `TurnStart` is durably releasable. Neither observation establishes a lock or lease against future owner writes.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/cognitive.read.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.read.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

Finalization is fail-closed. Invalid digests are invalid input; changed snapshot/read receipts are conflicts; owner unavailability/corruption does not silently fall back to the previously returned context. The infer worker does not send `TurnStart` with stale context when finalization fails. Because the exact dispatch intent is synced first, a finalization/cancellation failure is followed by a durable `stop_native_before_turn_start` transition that proves no provider turn was sent, releases the local slot, and preserves the dispatch identity for replay/audit.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Cognitive text remains `AdditionalContextKind::Untrusted` at the App Server boundary. The snapshot/read digests provide deterministic provenance and exact final compare-and-validate inputs; they are not authorization tokens and cannot grant model/tool/effect authority.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.read.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-cognitive-read/src/v2.rs](../../../codex-rs/hepta-cognitive-read/src/v2.rs), Agentd's bounded cognitive-context response, and the native host model-attachment limit.

Finalization intentionally pays for one additional owner cut plus deterministic bounded V2 read after the exact dispatch intent has been synced and immediately before model `TurnStart`. This cost is part of the correctness boundary; it must not be removed or replaced by a time-based cache without a separately proven owner lease/revocation mechanism.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Acquire a cut through the existing SQLite owner, then call the crate-native `ReadRequestV2` reader. Agentd compares exact revision/content digests and revalidates time/frontiers before response publication. A downstream model consumer must retain the returned `snapshot_digest`/`read_digest`, sync the exact durable dispatch intent, and invoke `CognitiveContextFinalize` immediately before `TurnStart`; the owner must reproduce those exact digests or reject the effect. A proven failure before `TurnStart` must durably stop/release the synced dispatch rather than fabricate provider completion. Neither the historical cut nor a successful finalization leases future external effects.

Current operating and state-format references:

- [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md).
- [docs/readiness/LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-cognitive-read/src/v2_tests.rs](../../../codex-rs/hepta-cognitive-read/src/v2_tests.rs) for deterministic V2 encoding, binding and bounds.
- [codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs); named case: `existing_sqlite_writes_are_readable_by_new_lane_c_after_reopen`.
- [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs); named case: `finalization_rejects_context_tombstoned_after_agentd_read`, which fixes the deterministic sequence `Lane C read -> Agentd receipt -> tombstone -> finalization deny`.
- [codex-rs/hepta-agent-protocol/src/lib.rs](../../../codex-rs/hepta-agent-protocol/src/lib.rs); named case: `cognitive_context_finalize_wire_round_trip_is_strict_and_bounded`.
- [codex-rs/hepta-infer-core/src/native_control.rs](../../../codex-rs/hepta-infer-core/src/native_control.rs); named case: `synced_dispatch_can_stop_before_turn_start_and_release_slot`, which persists and reopens a proven pre-turn stop after synced dispatch intent.
- [codex-rs/hepta-cognitive-read/src/authoritative_tests.rs](../../../codex-rs/hepta-cognitive-read/src/authoritative_tests.rs) remains qualification coverage for the deprecated non-production host-vector compatibility surface.

In `codex-rs`, run focused tests for `codex-hepta-memory`, `codex-hepta-cognitive-read`, `codex-hepta-agent-protocol`, `codex-hepta-agentd`, `codex-hepta-infer-core` and `codex-hepta-infer-worker-host`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.read.md) separately labels target acceptance designs.

A remaining qualification obligation is a full transport-level deterministic regression that drives a real/mocked Agentd control socket and App Server boundary through `CognitiveContext -> owner mutation -> CognitiveContextFinalize -> no TurnStart`. The owner-level race and the durable pre-turn stop are now covered separately, and production wiring invokes both boundaries, but that wider transport orchestration must not be claimed as passed until an exact-candidate receipt exists.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `MEM-READ-1-SNAPSHOT-PORT`

The bootstrap package is `MEM-READ-1-SNAPSHOT-PORT`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. `cognitive.read` now has named source-level product callers in Agentd and the native infer worker, so the implementation map records composition; this does not by itself establish independent qualification, operator acceptance, promotion or release.

The synchronous `AuthoritativeCognitiveSnapshotProvider`/`read_authoritative` surface remains source-compatible but is deprecated for production use and retained for qualification/compatibility. New production code must use the durable owner cut and explicit revalidation/finalization path rather than create a second provider semantics layer.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path production use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `cognitive.read`, the current machine-readable state is `implemented=true`, `composed=true`, `qualified=false`. `productionImplementation=true` in the implementation map means a real product code path exists; it is not shorthand for `productExecutionProved`, `independentAcceptance`, activation or release. Those claim-boundary fields remain false until their own evidence gates close.

For `cognitive.read`, this document grants no runtime, production-writer, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `MEM-READ-1-SNAPSHOT-PORT`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `cognitive-platform` / `agent-runtime`.
- Allowed write paths:
- `codex-rs/hepta-cognitive-read/**`
- Development predecessors:
- `MEM-0-TYPES`
- Activation predecessors:
- `MEM-0-TYPES`
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

The canonical readiness overlay binds `cognitive.read` to primary lane `LANE-C-MEMORY`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

### Readiness implementation work packages

The following additional work packages are source-planning envelopes introduced by the readiness overlay; they do not imply implementation or activation:

- `EMB-1-SENSOR-BUS-BODY-SCHEMA`

## 17. Source implementation receipt

The bootstrap source-location obligation for `cognitive.read` is implemented by work package `MEM-READ-1-SNAPSHOT-PORT` in:

- `codex-rs/hepta-cognitive-read`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. `IMPLEMENTATION_MAP.json` additionally binds composed cognitive-read source paths to exact Git tree/blob objects so source drift cannot remain silently marked composed. These receipts are source/composition evidence only. They grant no production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.

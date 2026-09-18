# cognitive.read technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `cognitive.read`

**Owner:** `cognitive-platform`

**Deputy:** `agent-runtime`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `MEM-READ-1-SNAPSHOT-PORT`

This stable document is the implementation guide for `cognitive.read`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Expose snapshot-bound cognitive reads without write authority.

The primary owner `cognitive-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `agent-runtime` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit integration callsite; product composition does not transfer ownership of another module's facts.

Plane `domain`, kind `port`, state model `stateless` and architecture role `contract` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-cognitive-read`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-cognitive-read`

Non-authoritative implementation evidence roots:

- `codex-rs/hepta-memory/src/lane_c_snapshot.rs` — canonical SQLite owner cut used as provider input.
- `codex-rs/hepta-agentd/src/cognitive_context.rs` — named product caller and final-use composition.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared root exists. Source references identify what can be inspected and invoked; only exact-candidate execution receipts establish that checks passed. This status does not establish operator acceptance, selection, promotion or release.

### Native source and scope

The authoritative product-facing implementation is [codex-rs/hepta-cognitive-read/src/authoritative.rs](../../../codex-rs/hepta-cognitive-read/src/authoritative.rs), including `AuthoritativeCognitiveSnapshotProvider`, `AuthoritativeReadRequestV1`, `AuthoritativeReadGuardV1` and `read_authoritative`. The bounded caller-supplied projection primitive remains [codex-rs/hepta-cognitive-read/src/v2.rs](../../../codex-rs/hepta-cognitive-read/src/v2.rs), including `ReadRequestV2`, `ReadResultV2` and `read_v2`.

`read_v2` is intentionally a lower-level primitive: it validates a supplied immutable snapshot but cannot establish that the bytes still represent the current authoritative retained generation. Product code must use the authoritative acquisition/read/revalidation path. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/cognitive.read.md#8-current-native-implementation) for exact composition status and remaining external evidence gates.

## 3. Boundary, responsibilities and non-goals

The SQLite owner exposes `CognitiveStore::lane_c_snapshot`, which materializes an owned immutable `DurableCognitiveSnapshot` from one SQLite read transaction. It authorizes the exact scope, preserves record and citation IDs, includes committed tombstones, and admits only verified, currently valid live heads.

The `hepta-agentd` product caller now composes that owner cut into an authoritative provider. It freezes a `LaneCGenerationVectorV1` containing the exact memory/source/tombstone/knowledge frontiers, KG generation, scope, purpose, lifecycle authority epoch, retrieval/query-encoder identities, optional pinned ranker payload digest and explicit identities for host dimensions not consumed by this path. It calls `read_authoritative`, uses the authoritative binding digest in context planning, then reacquires a new owner cut and requires `AuthoritativeReadGuardV1::revalidate` before returning the context.

The lifecycle authority epoch is not inferred from model text or caller input. Cognitive context is admitted only after `AgentdState::refresh_generation` reports a Running, ready generation. `state_control` passes that exact `current_generation` into the read; after the async read it refreshes lifecycle again, requires Running+Ready, and rejects if the generation differs from the originally bound epoch. Optional ranker registry currentness is also revalidated before return.

Direct dependencies:

- `cognitive.types`

Authoritative write domains:

None.

Explicitly denied capabilities:

- `write_authority`

The module accepts only registered, bounded, versioned inputs. It rejects stale leases, changed provider identity, changed generation vector, changed source snapshot, missing authority, scope/purpose mismatch and digest mismatch as hard failures. It never writes another owner's store.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, converting a frozen read into a lease over future effects, or converting qualification evidence into deployment authority.

## 4. Internal architecture and component decomposition

The bounded components are:

- `immutable owner-cut acquisition`
- `host generation-vector binding`
- `authoritative bounded projection`
- `scope and redaction filter`
- `optional ranking/context planning`
- `final-use provider revalidation`
- `outer lifecycle authority fence`

The key consistency rule is structural, not adapter convention. Production does not expose a moving `CognitiveSnapshotView` whose `visible()` and `fetch()` methods may observe different current states. `CognitiveStore::lane_c_snapshot` materializes one owned cut inside one SQLite transaction; the authoritative provider owns that cut; `AuthoritativeReadGuardV1` retains the exact acquisition and receipt identities that must match a newly acquired current provider before delivery.

Ingress validates identity, size, scope, purpose, authority epoch and deadline before domain logic. The deterministic projection core receives typed immutable values. Configuration/profile identities are frozen for one read and represented in the generation vector. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

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

The public Rust surface has two deliberately different correctness envelopes:

- `read_v2(snapshot, request)` is a lower-level projection over caller-supplied immutable bytes. It remains available for owner-local compatibility and tests.
- `read_authoritative(provider, now, acquisition, request)` is the product-level source-authority contract. It chooses the read snapshot from the provider, so the caller cannot substitute an unrelated snapshot digest, and returns a guard requiring current-provider revalidation before delivery.

Product callers must not advertise `read_v2` semantics as the authoritative contract. Every producer validates output before publication and binds semantic fields into the declared digest scope. Contract identifiers, meaning and authority interpretation cannot change in place.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

None.

Read-only data dependencies:

- the existing `hepta-memory` SQLite cognitive owner cut.

This module owns no persistence and writes no domain facts. The SQLite owner remains responsible for schema, integrity, recovery and revision lineage. `cognitive.read` consumes immutable snapshots and emits deny-all read receipts. A restored older database, correction, deletion, citation/source change, projection generation change or validity-time change is detected by exact owner-cut/vector/snapshot revalidation rather than treated as a compatible historical current state.

## 7. Runtime, concurrency and transaction model

`CognitiveStore::lane_c_snapshot` acquires all material needed for one scope in a single SQLite read transaction. The returned `DurableCognitiveSnapshot` is owned and immutable. No later database query mutates that cut.

Product execution follows:

1. refresh and admit the Running Agentd generation;
2. acquire one immutable SQLite cut;
3. bind the host generation vector and one-second authoritative deadline/lease ceiling;
4. execute the bounded authoritative projection;
5. intersect retrieval content with exact admitted record ID/revision/content digests;
6. perform bounded optional ranking and context planning;
7. reacquire a new SQLite cut and rebuild the same host vector;
8. require exact provider/vector/snapshot/lease revalidation;
9. revalidate optional ranker registry currentness;
10. return to `state_control`, which refreshes fleet lifecycle and requires Running+Ready again before the payload is emitted.

Any concurrent change that crosses these fences fails closed. A write after the last fence remains possible; this read-only module never claims to lease future effects.

## 8. Failure semantics, recovery and rollback

Freshness failures including deadline/lease expiry, scope/purpose/authority-epoch drift, owner-frontier drift, provider change, revoked/gone generation, changed vector or changed snapshot fail closed before context delivery. Invalid contract/digest/integrity state maps to corruption/invalid-input handling rather than fallback to an older view. Provider unavailability or indeterminate currentness returns unavailable; there is no stale-success fallback.

Rollback is source-compatible: the lower-level V2 primitive remains available, but the product caller must not silently fall back from authoritative acquisition to `read_v2`. A rollback that removes the authoritative product path must be an explicit source rollback, not runtime degradation.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent currentness checks. All authoritative read results retain `DENY_ALL` effect authority. Scope, purpose and lifecycle epoch are bound into acquisition; owner frontiers and host identities are bound into the generation vector; provider/vector/snapshot/read receipts are digest-bound; the guard refuses final use after lease expiry or currentness drift.

The selected learned ranker, when present, contributes its independently pinned payload digest to the generation vector and revalidates its registry witness before return. Absence of a ranker is represented by a domain-separated nonzero identity, not an ambiguous zero digest.

Negative tests cover scope/frontier/epoch drift, provider/vector drift, lease expiry, stale owner cuts, tombstone/correction invalidation, bounds and ranker currentness. Security review remains mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The low-level V2 projection hard-ceils encoded output at one MiB and result count at its registered bounds. The Agentd product context is stricter: the final JSON context is limited to 24 KiB, query length to 2048 bytes, result limit to 1..=4, and the authoritative context lease/deadline to one second.

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.read.md) records target/pilot ceilings separately from measured evidence. [Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

The production operating sequence is authoritative acquisition, bounded read, local bounded computation, current-provider reacquisition, guard revalidation, then outer Agentd lifecycle revalidation. Operators must not treat snapshot acquisition or successful projection alone as permission to deliver.

Current operating and state-format references:

- [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md).
- [codex-rs/hepta-agentd/src/cognitive_context.rs](../../../codex-rs/hepta-agentd/src/cognitive_context.rs).
- [docs/readiness/LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md).

Safe observability records digest identities/frontiers/error classes rather than memory content. Expired lease, generation gone, provider mismatch and authority-epoch mismatch are correctness failures, not retry-as-success signals.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-cognitive-read/src/v2_tests.rs](../../../codex-rs/hepta-cognitive-read/src/v2_tests.rs) — lower-level projection, ordering, missing/stale and resource-bound behavior.
- [codex-rs/hepta-cognitive-read/src/authoritative_tests.rs](../../../codex-rs/hepta-cognitive-read/src/authoritative_tests.rs) — scope/frontier/epoch binding plus delivery-time provider/vector/lease revalidation.
- [codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs) — one-owner SQLite cut, correction/tombstone/time/reopen/currentness behavior.
- [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs) — real SQLite provider-level adversarial tests for memory-frontier, authority-epoch and lease drift.
- [codex-rs/hepta-agentd/src/cognitive_context_budget_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_budget_tests.rs) — deterministic full-production-`read()` race: pause after authoritative acquisition during real ranker currentness, advance the real SQLite memory revision, release the read and require the final-use fence to fail closed.
- [codex-rs/hepta-agentd/src/cognitive_ranker_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_ranker_tests.rs) — outer control-path race: pause a live cognitive-context request after authoritative acquisition, advance fleet lifecycle from Running to Draining, release the read and require state-control to reject before payload delivery.

In `codex-rs`, focused source qualification is:

`just test -p codex-hepta-cognitive-read -p codex-hepta-memory -p codex-hepta-agentd`

The command is an invocation, not a stored result. Exact-head and merge-candidate CI receipts determine pass/fail status. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.read.md) separately records product composition and external gates.

## 13. Implementation sequence and work packages

Applicable work packages:

- `MEM-READ-1-SNAPSHOT-PORT`

The bootstrap package remains identified by the canonical plan. Source implementation now includes the authoritative library surface and named Agentd integration; canonical planning/activation/evidence predecessor graphs remain separately governed. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Independent acceptance, promotion and release are later gates and cannot be self-issued by this module.

## 14. Activation, compatibility and retirement

A named product caller now exists in `hepta-agentd` source. This is product source composition, not proof of deployment/target-host execution or operator acceptance. The product caller uses the authoritative path; shadow and qualification callers are not substitutes for that source fact.

Compatibility retains `read_v2` as a lower-level primitive. New product callers should compose `read_authoritative` and a current-provider final-use fence rather than directly calling `read_v2`. Retirement of the lower-level public surface requires all owner/test compatibility consumers migrated and a separate compatibility decision.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Product source composition requires a named caller; that caller is now `hepta-agentd` cognitive context. Qualification requires current exact-candidate evidence. Independent acceptance, activation, selection, promotion and release remain separate externally governed states.

For `cognitive.read`, the repository-controlled correctness gap described as “revision revalidation done but authority/generation/frontier/digest/lease pending product composition” is closed in source: the product path performs authoritative provider/vector/snapshot/lease revalidation and the outer Agentd caller revalidates lifecycle authority after the async read. This statement does not grant production deployment, provider, tool, network, filesystem, secret, fleet, acceptance, promotion or release authority.

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

The canonical readiness overlay binds `cognitive.read` to primary lane `LANE-C-MEMORY`. The following implementation-level specifications remain mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta. This overlay does not change acceptance, selection, promotion or release.

### Readiness implementation work packages

The following additional work packages are source-planning envelopes introduced by the readiness overlay; they do not imply implementation or activation:

- `EMB-1-SENSOR-BUS-BODY-SCHEMA`

## 17. Source implementation receipt

The bootstrap source-location obligation for `cognitive.read` is implemented by work package `MEM-READ-1-SNAPSHOT-PORT` in:

- `codex-rs/hepta-cognitive-read`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. Product composition additionally touches the existing owners `hepta-memory` and `hepta-agentd` without transferring their ownership. This receipt is source implementation evidence only. It grants no production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.

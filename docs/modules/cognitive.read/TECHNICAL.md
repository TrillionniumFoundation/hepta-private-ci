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

Declared exclusive target root:

- `codex-rs/hepta-cognitive-read`

The root is materialized. The current typed-local product port is [`read_ids_v1`](../../../codex-rs/hepta-cognitive-read/src/ids.rs) with `ReadIdsRequestV1`, `ReadIdsResultV1`, `ReadFieldV1` and `ReadProjectionRecordV1`. The compatibility `read_v2` projection remains in [`v2.rs`](../../../codex-rs/hepta-cognitive-read/src/v2.rs).

The durable source owner is not this crate. Product composition acquires one authorized `DurableCognitiveSnapshot` from [`hepta-memory`](../../../codex-rs/hepta-memory/src/lane_c_snapshot.rs), validates bounded retrieval candidates by exact ID/revision/content digest, and performs capability-gated final-use revalidation in Agentd immediately before the native worker issues physical `TurnStart`.

The canonical work package `MEM-READ-1-SNAPSHOT-PORT` is `source_implemented_execution_pending`. That state means source and composition exist while exact-candidate execution evidence remains pending. It does not imply independent acceptance, activation, promotion or release.

The implementation map keeps the repository-wide generated `sourceBase` baseline intact and separately records the fresh reviewed implementation base. A generated-map baseline is not a claim that no later source exists.

## 3. Boundary, responsibilities and non-goals

Mission: expose coherent, bounded, read-only cognitive projections without write authority.

The product path is:

```text
CognitiveStore::lane_c_snapshot
→ DurableCognitiveSnapshot::read_ids
→ Agentd cognitive_context
→ cognitive.context.revalidate@1
→ native App Server TurnStart
```

The SQLite owner authorizes the exact principal/scope before reading. `read_ids_v1` then resolves only requested current heads, reports missing IDs explicitly and projects only the requested optional fields. Results always retain `AuthorityPosture::DENY_ALL`.

The current durable SQLite schema has no memory-kind discriminator. Its Lane C adapter therefore advertises `DURABLE_SQLITE_MEMORY_KIND = MemoryKind::Fact`. `Episode`, `Preference` and `Procedure` remain valid cognitive type values but are not claimed for this durable owner until an explicit owner migration qualifies them.

Direct dependency:

- `cognitive.types`

Authoritative write domains: none.

Explicitly denied capability:

- `write_authority`

Non-goals include becoming a state store, opening SQL from the read crate, inventing a second cognitive owner, caching cross-principal projections, treating V2 bytes as a wire protocol, leasing future external effects, or converting source/test evidence into deployment authority.

## 4. Internal architecture and component decomposition

The implemented components are:

- owner-acquired coherent snapshot;
- validated current-head map;
- exact-ID field projection;
- canonical request/result digest binding;
- consumer integration and final-use revalidation.

The module itself is stateless. It owns no cache, pin registry, lease table, descriptor pool, durable record or background worker. Snapshot acquisition and SQL transaction lifetime belong to the existing `hepta-memory` owner. Dropping or cancelling a read drops ordinary in-memory values; there is no module-owned long-lived history pin.

`read_ids_v1` validates the entire supplied snapshot before projecting an exact bounded ID set. Duplicate IDs/fields, more than 512 IDs, malformed snapshots and oversize results fail closed. Exact-ID reads are all-or-error and never silently return a prefix.

The composed Agentd path builds an ID-indexed admitted-record map once, avoiding the former candidate-by-`read.records().iter().any(...)` scan. Ranking and byte budgeting happen only after owner-cut admission.

## 5. Contracts, ports and compatibility

Produced contracts:

- `ModulePort::cognitive.read::compact.engine`
- `ModulePort::cognitive.read::context.compiler`
- `ModulePort::cognitive.read::memory.federation`
- `ModulePort::cognitive.read::memory.retrieval`
- `ModulePort::cognitive.read::neuron.runtime`
- `ModulePort::cognitive.read::objective.compiler`
- `ModulePort::cognitive.read::utility.ndu`

Consumed contract:

- `ModulePort::cognitive.types::cognitive.read`

The registered contract transport class permits `typed_local_or_versioned_wire`. The current native ModulePort implementation is the typed-local `read_ids_v1` Rust API. Its in-process types are the contract surface.

The canonical bytes produced by `read_v2` and `ReadIdsResultV1` are integrity/digest representations. They are not admitted cross-process protocols and are not silently promoted into `PROTOCOL_SCHEMAS.json`. A future wire transport requires a separately versioned protocol admission.

The existing Agentd control protocol is a separate host-integration boundary. The pre-existing `CognitiveContextSnapshot` response shape remains unchanged; final-use validation is additive and capability-gated as `cognitive.context.revalidate@1`. New workers fail closed when cognitive context is requested from an owner that does not advertise that capability.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains: none.

Read-only input: an already authorized `CognitiveSnapshot` value supplied by the existing cognitive owner.

The read crate contains no persistence and therefore owns no migration. The physical SQLite schema, open/recovery behavior, correction lineage and tombstones remain under `hepta-memory::CognitiveStore`.

The current durable schema's lack of a memory-kind column is treated as an explicit capability limit, not inferred polymorphism: durable Lane C records project as `Fact` only. Expanding that set requires an owner migration, backward-compatibility policy and tests before the read port may expose more durable kinds.

## 7. Runtime, concurrency and transaction model

`CognitiveStore::lane_c_snapshot` authorizes the caller and materializes one coherent scope inside a single SQLite read transaction. The transaction is committed before the immutable `DurableCognitiveSnapshot` is returned.

The read crate performs no I/O and requires no lock. It validates/canonicalizes the supplied snapshot and resolves current heads into a `BTreeMap`; exact requested IDs are then keyed lookups.

The Agentd consumer obtains retrieval candidates, validates them against the same cut, ranks only admitted records, applies the shared final-consumer budget, and revalidates the cut before returning. The native inference worker additionally negotiates `cognitive.context.revalidate@1` and asks the owner to reacquire the current snapshot and recheck every selected ID/revision/content digest before `TurnStart`.

That final-use observation is intentionally not described as a lease: a concurrent write after the check remains possible and no read path blocks future owner mutations.

## 8. Failure semantics, recovery and rollback

Snapshot integrity, duplicate/oversize requests and malformed typed-local inputs are rejected. Resource exhaustion maps to unavailable; caller/request errors map to invalid; owner-store integrity violations map to corrupt; stale final-use state maps to conflict/request rejection. Agentd no longer classifies every read-port failure as store corruption.

Correction, committed tombstone, validity expiry, snapshot-generation change, wrong principal or selected-content substitution makes an old context fail final-use validation.

Rollback restores the predecessor read/consumer path together. It must not leave a worker that attaches cognitive context without a negotiated final-use validation capability. V2 canonical bytes remain internal integrity evidence across rollback and never become a compatibility wire format.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

Current enforced source bounds include:

- `read_ids_v1`: at most 512 IDs;
- module-native encoded result ceiling: at most 1 MiB;
- current composed Agentd/model context: one shared `MAX_COGNITIVE_CONTEXT_BYTES = 8 KiB`;
- durable materialization: the revision/citation/source bounds documented by `LANE_C_SQLITE.md`;
- current Agentd selected result limit: 1..=4.

Exact-ID validation builds the current-head map once and then performs keyed lookups. It no longer intersects retrieval candidates with a globally truncated first-1,024-record read, and it no longer linearly scans the returned read set for every candidate.

These are capacity and algorithmic bounds, not production performance measurements. Target-host p50/p95/p99 latency, CPU, RSS and SQLite evidence remain qualification requirements and must not be invented from unit tests.

## 11. Observability and operations

The operational sequence is:

1. acquire the owner cut;
2. retrieve bounded candidates;
3. exact-ID validate against that cut;
4. rank and budget;
5. revalidate before Agentd response publication;
6. negotiate `cognitive.context.revalidate@1`;
7. revalidate the selected ID/revision/content bindings against a newly acquired current snapshot immediately before model `TurnStart`.

The same 8 KiB serialized cognitive-context budget is exported by the Agentd protocol and consumed by both Agentd and the native inference worker, preventing producer/consumer budget drift.

Current operating references:

- [`codex-rs/hepta-memory/LANE_C_SQLITE.md`](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md)
- [`docs/readiness/LANE_B_NATIVE_HOST.md`](../../readiness/LANE_B_NATIVE_HOST.md)

## 12. Verification and qualification

Focused source tests include:

- [`ids_tests.rs`](../../../codex-rs/hepta-cognitive-read/src/ids_tests.rs): exact ID beyond the legacy 1,024 prefix, field projection, missing IDs and request bounds;
- [`v2_tests.rs`](../../../codex-rs/hepta-cognitive-read/src/v2_tests.rs): canonical V2 envelope and byte limits;
- [`tombstone_resurrection_tests.rs`](../../../codex-rs/hepta-cognitive-read/src/tombstone_resurrection_tests.rs): terminal deletion lineage;
- [`lane_c_snapshot_tests.rs`](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs): SQLite cut, correction, expiry, scope, reopen and rollback witness;
- [`cognitive_ranker_tests.rs`](../../../codex-rs/hepta-agentd/src/cognitive_ranker_tests.rs): real control socket, advertised revalidation capability and stale-final-use rejection;
- [`cognitive_context_budget_tests.rs`](../../../codex-rs/hepta-agentd/src/cognitive_context_budget_tests.rs): post-ranking shared response budget.

In `codex-rs`, the focused invocation remains `just test -p codex-hepta-memory -p codex-hepta-cognitive-read`, with Agentd/native-worker tests required for the composed path.

Test files are not pass receipts. Exact-head and deterministic synthetic-merge execution must be read from the current candidate CI. Independent semantic review, target-host qualification, operator acceptance, promotion and release are separate evidence gates.

## 13. Implementation sequence and work packages

Applicable work packages:

- `MEM-READ-1-SNAPSHOT-PORT`

The bootstrap package is `MEM-READ-1-SNAPSHOT-PORT`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `cognitive.read`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `MEM-READ-1-SNAPSHOT-PORT`

- State: `source_implemented_execution_pending`; priority: `2`; parallel class: `contract_coordinated`.
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

The bootstrap source implementation for `cognitive.read` is materialized by work package `MEM-READ-1-SNAPSHOT-PORT` in:

- `codex-rs/hepta-cognitive-read`

The source package is now classified `source_implemented_execution_pending`. `.github/workflows/hepta-consolidated-source.yml` is the intended exact-candidate gate for closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. Until a current candidate run is observed, this document does not claim those checks passed. Even a passing source receipt grants no independent acceptance, model/provider authority, promotion or release.

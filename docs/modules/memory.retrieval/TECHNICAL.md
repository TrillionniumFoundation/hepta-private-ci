# memory.retrieval technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `memory.retrieval`

**Owner:** `cognitive-platform`

**Deputy:** `performance`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `MEM-2-RETRIEVAL`

This stable document is the implementation guide for `memory.retrieval`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Produce explainable, revalidated retrieval results on the local hot path without central synchronous RPC.

The primary owner `cognitive-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `performance` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `engine`, state model `read_only` and architecture role `execution_plant` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-memory-retrieval`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-memory-retrieval`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The product-composed ranking source is [codex-rs/hepta-memory-retrieval/src/owner_rank.rs](../../../codex-rs/hepta-memory-retrieval/src/owner_rank.rs); observed identifiers include `OwnerRankReceiptV1` and `rank_owner_candidates`. Additional native surfaces include `compile_cue`, `build_candidate_union`, `recall`, `RetrievalReceiptV2`, `retrieve_v2` and `binding_digest_v2`. The legacy V1 `retrieve` function is crate-private; external consumers use the full-input-bound V2 or the product-composed owner-observation ranker. This is a source navigation binding, not proof that every target operation or production consumer exists. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/memory.retrieval.md#8-current-native-implementation) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/memory.retrieval.md) for the implemented subset and remaining product work.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `cognitive.read`
- `knowledge.graph`

Authoritative write domains:

None.

Explicitly denied capabilities:

- `write_authority`
- `central_rpc_hot_path`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `bounded input stage`
- `deterministic algorithm core`
- `generation publisher`
- `checkpoint and recovery layer`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `ModulePort::memory.retrieval::prompt.optimizer`

Consumed contracts:

- `DomainRead::knowledge_graph_projectionV1`
- `DomainRead::prompt_factor_graph_projectionV1`
- `ModulePort::cognitive.read::memory.retrieval`
- `ModulePort::knowledge.graph::memory.retrieval`

Critical protocol schemas:

None.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

None.

Read-only data dependencies:

- `knowledge_graph_projection`
- `prompt_factor_graph_projection`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/memory.retrieval.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/memory.retrieval.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/memory.retrieval.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/memory.retrieval.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/memory.retrieval.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Native owner-rank, V2 and generation-bound ranking now cap candidate inputs at 512 and returned results at 16. HNMF graph ceilings remain target design bounds, not measurements or proof that graph settling is product-composed.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Embed retrieval against an authorized coherent read cut. The current Agentd host obtains the SQLite owner's bounded `RetrievalObservation`, intersects it with the exact Lane C read cut, passes the admitted records and aggregate owner score through `rank_owner_candidates`, optionally applies the pinned learned ranker only to those results, applies the response byte/result budget, then revalidates the exact selected memory/source/citation/KG bindings before publication. The GraphOneHop observation additionally preserves canonical persisted KG temporal/causal/procedural/contradiction relation tags, and the owner-rank receipt binds their mapped evidence channels without reinterpreting aggregate RRF as normalized channel scores or calibrated OOD. `omitted_records` still reports Lane C read truncation; neither the owner observation nor this product composition promises complete recall outside its bounded generator limits.

Current operating and state-format references:

- [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md).
- [docs/readiness/LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs); named cases include `channel_completion_order_cannot_change_union_or_recall`, `below_floor_top_k_candidate_is_omitted_and_cannot_poison_recall` and `lexical_only_ablation_has_distinct_policy_union_and_packet_identity`.
- [codex-rs/hepta-memory-retrieval/src/owner_rank_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/owner_rank_tests.rs); covers full owner-observation binding, semantic evidence-channel binding and product capacity.
- [codex-rs/hepta-memory/src/cognitive_retrieval_observation_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_retrieval_observation_tests.rs); named case: `graph_observation_preserves_canonical_relation_semantics`.
- [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs); named case: `post_ranking_withdrawal_fails_closed_before_context_delivery`.
- [codex-rs/hepta-memory-retrieval/src/lib_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/lib_tests.rs); legacy V1-only compatibility tests remain test-scoped.

In `codex-rs`, run `just test -p codex-hepta-memory-retrieval`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/memory.retrieval.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `MEM-2-RETRIEVAL`

The bootstrap package is `MEM-2-RETRIEVAL`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. The owner-observation ranking path now has the named caller `hepta-agentd::cognitive_context`; this does not by itself establish the still-unimplemented HNMF channel/engram pipeline. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `memory.retrieval`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `MEM-2-RETRIEVAL`

- State: `planned`; priority: `2`; parallel class: `contract_first_parallel`.
- Owner/deputy: `cognitive-platform` / `performance`.
- Allowed write paths:
- `codex-rs/hepta-memory-retrieval/**`
- Development predecessors:
- `MEM-0-TYPES`
- Activation predecessors:
- `MEM-1-STORE`
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

The canonical readiness overlay binds `memory.retrieval` to primary lane `LANE-C-MEMORY`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `memory.retrieval` is implemented by work package `MEM-2-RETRIEVAL` in:

- `codex-rs/hepta-memory-retrieval`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.

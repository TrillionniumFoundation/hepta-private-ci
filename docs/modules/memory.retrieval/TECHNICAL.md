# memory.retrieval technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `memory.retrieval`

**Owner:** `cognitive-platform`

**Deputy:** `performance`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `MEM-2-RETRIEVAL`

This stable document is the implementation guide for `memory.retrieval`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness, source composition, exact-candidate execution, independent acceptance, promotion and release remain distinct claims.

## 1. Identity, mission and ownership

Produce explainable, bounded, owner-backed and revalidated retrieval results on the local hot path without central synchronous RPC.

The primary owner `cognitive-platform` controls changes inside the declared target root and is accountable for correctness, backward compatibility, evidence and rollback. The deputy `performance` reviews public contracts, resource limits, determinism, concurrency and activation behavior. The module is read-only and may optimize locally, but cannot own the SQLite memory facts/indexes, mint authority, infer external completeness from a digest, or claim global optimality.

## 2. Source binding and implementation status

Declared and resolved target root:

- `codex-rs/hepta-memory-retrieval`

Current native product surfaces are:

- `compile_cue` and `retrieve_product_v1` in `src/product.rs`;
- complete-input compatibility `retrieve_v2` in `src/v2.rs`;
- generation-bound `build_candidate_union` and compatibility `recall` in `src/generation_bound.rs`;
- strict product `recall_v2` in `src/recall_v2.rs`.

The named product caller is `codex-rs/hepta-agentd/src/cognitive_context.rs::read`. It composes the canonical SQLite owner observation through `retrieve_product_v1`, batch-revalidates selected owner bindings and revalidates the complete Lane-C cut before response publication.

This closes the earlier repository-controlled “no product caller / caller-supplied-only product admission” gap for the existing SQLite retrieval provider. It does **not** prove the complete target HNMF pipeline: vector/causal/procedural generators, calibrated contradiction/OOD producers, engram settling, actual model-turn consumption and independent qualification remain open. See the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/memory.retrieval.md).

## 3. Boundary, responsibilities and non-goals

Direct dependencies remain:

- `cognitive.read`
- `knowledge.graph`

The current physical owner dependency is the existing `hepta-memory::CognitiveStore`; it is an implementation integration, not a transfer of authoritative write ownership.

Authoritative write domains: none.

Explicitly denied capabilities:

- `write_authority`
- `central_rpc_hot_path`
- implicit model/provider authority
- second memory/index database

The module validates bounded typed inputs and content bindings. Owner authentication/freshness comes from the owner read path and explicit revalidation, not from constructing native Rust values. A receipt can bind what was supplied; it cannot by itself prove that an external generator was complete or current.

## 4. Internal architecture and canonical ranking topology

The composed product path is deliberately single-spined:

1. `CognitiveStore::observe_memory_retrieval` executes the existing bounded SQLite generator in one owner read transaction. Current real channels are Memory FTS, entity FTS, graph one-hop and recency; the owner observation binds channel limits, scores and revalidation facts.
2. Agentd obtains a coherent Lane-C read cut and admits only exact live record ID/revision/content-digest matches from that same owner surface.
3. `retrieve_product_v1` binds the owner-observation digest plus the complete admitted candidate set, enforces the product 512-candidate/16-result ceiling and performs deterministic pre-admission ranking.
4. The selected `MemoryRevalidationBinding` set is revalidated together in one SQLite transaction. Stale/corrected/tombstoned/citation-drifted/expired/KG-drifted entries are not attached.
5. An explicitly configured `PinnedCognitiveRanker` may reorder only the already admitted and revalidated product set. It cannot resurrect a record that the owner/Lane-C/product admission rejected.
6. The caller applies its smaller response count/byte budget, runs context planning and finally revalidates the complete Lane-C cut before publishing the response.

This ordering is the canonical precedence among the previous three ranking semantics: owner retrieval first, deterministic `memory.retrieval` admission second, optional learned reordering third.

The fuller target architecture additionally includes cue compilation from the actual objective/context/model tuple, vector/causal/procedural/contradiction generation, bounded local engram expansion, <=4 settling steps and population competition. Missing components must be added through their real owners; no channel may be fabricated by relabeling another score.

## 5. Contracts, ports and compatibility

Produced registered contract:

- `ModulePort::memory.retrieval::prompt.optimizer`

Consumed registered contracts:

- `DomainRead::knowledge_graph_projectionV1`
- `DomainRead::prompt_factor_graph_projectionV1`
- `ModulePort::cognitive.read::memory.retrieval`
- `ModulePort::knowledge.graph::memory.retrieval`

The native product types are not automatically wire/ModulePort contracts. `retrieve_product_v1` is the required native product admission surface for the current owner-backed path. Legacy `retrieve` remains only for compatibility and is deprecated for product callers because its V1 digest binds the returned top-k rather than the complete input. `retrieve_v2` preserves the historical ranking bytes while binding the complete caller-supplied input. `ProductRetrievalReceiptV1` adds the owner-observation digest and strict product limits.

Compatibility `recall` remains available for prior native fixtures. Product generation-bound callers use `recall_v2`; V2 has a separate receipt domain because its risk aggregation semantics intentionally differ from V1.

## 6. Data authority, persistence and migrations

`memory.retrieval` owns no authoritative or rebuildable database. The existing `hepta-memory` SQLite owner remains the sole physical content/index owner. Ranking and recall receipts are stateless values.

A future cache, if admitted, is rebuildable only and must bind the full read snapshot key, cue digest, retrieval/encoder profile, quotas, truncation policy and current revocation/tombstone frontier. Cache restore can never override a newer correction or deletion. Candidate/propensity facts used for causal evaluation must flow through the learning ledger owner instead of becoming hidden mutable retrieval state.

Because the current product integration adds no schema, rollback does not require a data migration: remove the product composition and return to the predecessor read path while preserving owner facts and compatibility receipt interpretation.

## 7. Runtime, concurrency and transaction model

Owner generation and owner revalidation each execute inside bounded SQLite read transactions. `memory.retrieval` itself performs no I/O and has no lock or mutable singleton. The product caller may perform work between those owner transactions, so freshness is established by the selected-binding batch revalidation and the final complete-cut revalidation rather than by assuming a historical snapshot is a future lease.

The exact final local-check-to-network-send window remains a host concern. The current Agentd context path returns a revalidated context; physical model dispatch has its own owner/generation checks and does not become atomic with SQLite mutation merely because retrieval succeeded.

## 8. Failure semantics, recovery and rollback

Fail closed on malformed digests, duplicate identities, tombstones, snapshot mismatch, invalid limits, owner-observation absence, arithmetic overflow or a result that cannot be mapped back to the admitted owner cut.

A stale selected owner binding is omitted from the candidate attachment set; the final Lane-C cut revalidation rejects a response assembled across a changed/rolled-back cut. An unavailable/revoked learned ranker closes the learned-ranked read rather than silently using a stale model. No retry may reinterpret an uncertain external effect as retrieval success.

Compatibility rollback preserves V1/V2 bytes. Product callers must not downgrade provenance semantics by treating an old V1 receipt as evidence that omitted candidates or owner provenance were bound.

## 9. Security, privacy and threat controls

The module remains deny-all for runtime/effect authority. Product receipts contain digests, IDs, counts and scores, not credentials or unrestricted source payloads. The real owner authorizes scope before generating candidates. Lane-C admission and revalidation prevent a caller from turning an arbitrary candidate into an attached memory merely by constructing a native retrieval struct.

Threat tests include tombstones, duplicate candidates, stale generations, complete-input binding, owner-observation binding, oversize inputs and low-ranked risk-poisoning cases. New network/model/effect boundaries require their owning authority and separate review.

## 10. Performance, capacity and hot-path policy

The product admission ceiling is now source-enforced:

- <=512 product candidates;
- <=16 product retrieval/recall results.

Compatibility V1/V2 ranking retains the historical <=16,384 candidates / <=256 results so existing native digest semantics are not silently changed; that surface is not the product hot path.

Remaining target HNMF ceilings are:

- <=4096 nodes;
- <=32768 synapses;
- <=4 settling steps;
- <=64 active units per population.

Those HNMF ceilings are not yet execution measurements because that engine is not yet composed. Qualification must report owner channel-limit observations, product omission counts, latency distribution, revalidation cost, graph expansion and any learned-ranker cost. No full-store scan or central synchronous RPC is permitted.

## 11. Observability and operations

The SQLite owner exposes per-channel candidate counts and `LimitReached`/`Exhausted` observations plus an observation digest. Product retrieval binds that observation digest, making the exact bounded owner enumeration distinguishable from an arbitrary caller candidate list.

The Agentd response continues to report Lane-C read truncation through `omitted_records`; that field does not claim global recall completeness. Retrieval outside the admitted bounded owner/read surface may exist. Operators must distinguish owner-channel truncation, Lane-C read truncation, product top-k omission, response byte-budget omission and explicit abstention.

Current operating references:

- [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md)
- [docs/readiness/LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md)

## 12. Verification and qualification

Focused source tests include:

- `src/product_tests.rs`: cue construction, owner-observation binding, complete-input binding and 512/16 product limits;
- `src/v2_tests.rs`: V1 compatibility and complete supplied-input binding;
- `src/generation_bound_tests.rs`: deterministic channel union, stale generation, contradiction/OOD/coverage fail-closed behavior;
- `src/recall_v2_tests.rs`: low-ranked unrelated OOD/contradiction poisoning resistance, top-k contradiction protection, top-k coverage semantics and strict limits;
- `hepta-memory/src/cognitive_retrieval_tests.rs`: real owner retrieval/revalidation behavior and coherent batch revalidation under concurrent writes;
- `hepta-agentd/src/cognitive_context_tests.rs` and `cognitive_context_budget_tests.rs`: real SQLite context path, withdrawal behavior, byte-budget ordering and learned-ranker composition.

Run `just test -p codex-hepta-memory-retrieval` in `codex-rs` plus the affected Agentd/owner tests, all-target compilation, strict Clippy and merge-candidate checks. File existence is not a pass receipt. Exact PR/head workflow results are the repository evidence for this candidate.

RET status at source-design level:

- RET-01: native regression exists.
- RET-02: V1 and V2 native regressions exist.
- RET-03: product revalidation mechanism exists and owner coherent-batch concurrency coverage exists; an exact Agentd between-ranking-and-revalidation injected-race regression is still desirable.
- RET-04: longitudinal/ablation experiment evidence remains open.

## 13. Implementation sequence and work packages

Applicable work package: `MEM-2-RETRIEVAL`.

Repository work proceeds in this order: owner-backed product composition; strict product limits and provenance binding; canonical ranking precedence; generation-bound V2 risk semantics; machine-readable map/evidence refresh; exact-head/merge qualification; then missing target channels/HNMF/model-turn integration and external acceptance.

The canonical registry may continue to describe the package conservatively until the exact candidate evidence updates its claim boundary. Source existence or a draft PR alone does not authorize activation/release.

## 14. Activation, compatibility and retirement

A named source-level product caller now exists in Agentd, but module-wide activation remains broader than that fact. The current composed path is a read-only local context path. Full target activation still requires the actual model-turn consumer/model tuple, remaining generator/HNMF capabilities, target-host measurements and evidence gates.

V1 retrieval and V1 recall are compatibility surfaces. New product code uses `retrieve_product_v1` and, when generation-bound recall is composed, `recall_v2`. Retirement of compatibility APIs requires repository-wide caller migration, receipt/oracle compatibility review and independent acceptance; removal is not implied by deprecation.

## 15. Definition of module completion

Documentation completion: this guide, canonical registries, current implementation map and closed-world validation.

Source/product-composition completion for the **currently implemented SQLite-backed subset**: native product API, named owner-backed caller, strict resource bounds, source revalidation and passing exact-candidate tests.

Full target module completion additionally requires the missing real channel generators, calibrated risk production, bounded engram/HNMF execution, model-turn consumption, RET-04 outcome evidence, target-host qualification and independent acceptance.

Selection, promotion and release remain separate externally governed states. This document grants no model/provider/effect/release authority.

### Work-package execution envelope

#### `MEM-2-RETRIEVAL`

- Owner/deputy: `cognitive-platform` / `performance`
- Allowed primary write path: `codex-rs/hepta-memory-retrieval/**`
- Integration changes to the owner/caller require their normal cross-owner review.
- Development predecessor: `MEM-0-TYPES`
- Activation predecessor: `MEM-1-STORE`
- Required evidence includes source identity, source inventory, focused/package tests, all-target check, strict lint, clean state, exact-head execution and deterministic merge-candidate execution.
- Stop on authority violation, base drift, claim/evidence mismatch, cross-owner write or unbounded resource/retry behavior.

## 16. V8.2 pre-coding implementation-readiness overlay

Primary lane: `LANE-C-MEMORY`.

Mandatory readiness references remain:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

No new authority is created by owner-backed composition. Runtime admission still verifies current source/configuration/authority identities at the boundary that consumes them. This overlay does not imply independent acceptance, selection, promotion or release.

## 17. Source implementation receipt

The declared source root exists at `codex-rs/hepta-memory-retrieval`. The current source candidate additionally changes the named caller in `codex-rs/hepta-agentd` to consume the product retrieval admission API and the canonical owner observation/revalidation APIs.

`.github/workflows/hepta-consolidated-source.yml` and the affected Agentd/repository workflows are the execution gates for this candidate. Until those exact-candidate runs pass, this section records source intent and inspectable implementation only. Even after source qualification passes, independent semantic review, target-host/product execution evidence, operator acceptance, promotion and release remain separate gates.

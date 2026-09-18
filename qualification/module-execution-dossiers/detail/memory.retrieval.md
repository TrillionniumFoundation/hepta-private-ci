# memory.retrieval: implementation design

Parent: `docs/modules/memory.retrieval/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: bounded native ranking, V2 input binding, deterministic cue compilation, typed generator batches and the canonical SQLite-owner adapter are implemented. Agentd ranks the complete bounded owner observation before legacy top-four truncation. Generation-bound recall is still not product-composed because the runtime caller does not yet supply the complete host-frozen generation/objective context; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-memory-retrieval`.
Packages: `MEM-2-RETRIEVAL`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`compile_cue(objective, approved_context, snapshot) -> MemoryCueV1`; `retrieve(cue, channel_budgets) -> CandidateUnion`; `recall(candidates, engram_snapshot, policy) -> RecallPacketV1 | Abstain`. Channels are explicitly lexical, vector, entity, temporal, causal, procedural and contradiction support where implemented. Each returns scoped IDs, source revisions and a score/support receipt, not unrestricted source payload.

## 3. State records and transaction design

No source-fact writer. A rebuildable query/recall cache binds the full read snapshot key, cue digest, retrieval/encoder profile, source quotas and truncation policy. Engram/synapse generations are supplied as immutable projections. Candidate-set and propensity facts are appended only through learning.ledger's owner port.

## 4. Deterministic algorithm and scheduling

Run bounded channels in parallel; stable-union by exact event revision; deduplicate; apply source/modality quotas and deterministic pre-assignment truncation; expand only a bounded local engram graph; settle at most four steps; apply per-population competition; detect contradictions; calibrate recall/abstain; revalidate exact source support before returning. Vector closeness does not prove truth; incompatible facts are not averaged into a new fact.

## 5. Capacity and performance profile

Use HNMF reference ceilings: <=512 candidate events, <=4096 nodes, <=32768 synapses, <=4 settling steps and <=16 returned events, with <=64 active units per population. Report channel omissions, graph expansion, p99 latency and source revalidation cost; no full-store scan or central synchronous RPC.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- RET-01: channel completion order/permutation yields an identical canonical candidate union.
- RET-02: high-risk contradictory support forces abstention/slow path.
- RET-03: revoked/stale source after ranking cannot be attached to a model request.
- RET-04: no-intervention, lexical-only, no-recurrence and no-inhibition baselines measure independent utility and resource cost.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

C1 first changes a bounded read-only ranking/recall decision. Keep complete legal candidates and assignment propensities for causal evaluation. Rollback restores compatible retrieval/engram profiles and rebuilds caches under current tombstones, not old cached answers.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `retrieve_v2` in [codex-rs/hepta-memory-retrieval/src/v2.rs](../../../codex-rs/hepta-memory-retrieval/src/v2.rs); `compile_cue` in [codex-rs/hepta-memory-retrieval/src/generation_bound.rs](../../../codex-rs/hepta-memory-retrieval/src/generation_bound.rs); `adapt_owner_observation` in [codex-rs/hepta-memory-retrieval/src/owner_adapter.rs](../../../codex-rs/hepta-memory-retrieval/src/owner_adapter.rs); `build_candidate_union_from_batches` in [codex-rs/hepta-memory-retrieval/src/generator_contract.rs](../../../codex-rs/hepta-memory-retrieval/src/generator_contract.rs); `recall_from_batches` in [codex-rs/hepta-memory-retrieval/src/generator_contract.rs](../../../codex-rs/hepta-memory-retrieval/src/generator_contract.rs); low-level `build_candidate_union` and `recall` remain in [codex-rs/hepta-memory-retrieval/src/generation_bound.rs](../../../codex-rs/hepta-memory-retrieval/src/generation_bound.rs). The typed batch path enforces the HNMF 512-candidate/16-result product ceilings while preserving the wider native library ceiling for compatibility.
- **State and recovery:** Native receipts bind the supplied candidate set, including omitted candidates, and retain explicit channel/score/generation data. The SQLite owner now exposes exact pre-fusion per-channel ranks plus a digest of the revision/source revalidation facts for every bounded observed candidate. The canonical owner adapter derives retrieval scores only from those observed ranks; caller-supplied replacement scores are not used on this path. Ranking remains stateless; existing hepta-memory SQLite retrieval remains the physical content/index owner.
- **Source tests:** [codex-rs/hepta-memory-retrieval/src/v2_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/v2_tests.rs), [codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs), [codex-rs/hepta-memory-retrieval/src/generator_contract_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/generator_contract_tests.rs), [codex-rs/hepta-memory-retrieval/src/owner_adapter_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/owner_adapter_tests.rs), [codex-rs/hepta-memory/src/cognitive_retrieval_observation_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_retrieval_observation_tests.rs), [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs), and [codex-rs/hepta-agentd/src/cognitive_retrieval_adapter_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_retrieval_adapter_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md), [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md).
- **Current product seam:** Agentd now consumes `CognitiveStore::observe_memory_retrieval` before the legacy top-four cut, so an explicitly selected learned ranker can reorder the complete bounded owner set. Raw memory content is resolved only after one-snapshot owner revalidation. `adapt_sqlite_owner_observation` converts that same owner observation into typed `memory.retrieval` batches when a host supplies the exact frozen Lane-C generation-vector digest.
- **Remaining work:** The product caller must obtain the complete frozen `LaneCGenerationVectorV1`, objective and approved-context digests from their actual owners, call `compile_cue`, and invoke `recall_from_batches` before final attachment. Vector, causal, procedural and contradiction-support generators remain separate capabilities and must identify their real producer/profile rather than being inferred from SQLite lexical/entity/recency evidence. Engram expansion, recurrent settling, sparse population competition, causal propensity logging, product performance qualification and independent acceptance remain open.

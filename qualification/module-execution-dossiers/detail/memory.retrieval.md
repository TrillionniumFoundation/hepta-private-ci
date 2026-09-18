# memory.retrieval: implementation design

Parent: `docs/modules/memory.retrieval/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: bounded native ranking, V2 input binding, cue compilation and generation-bound recall implemented. Agentd now composes the canonical SQLite owner through `retrieve_v2` before optional learned reranking; remaining generation-bound channel integration and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

- **Implemented entrypoints:** `compile_cue`, `build_candidate_union` and `recall` in [codex-rs/hepta-memory-retrieval/src/generation_bound.rs](../../../codex-rs/hepta-memory-retrieval/src/generation_bound.rs); `retrieve_v2` in [codex-rs/hepta-memory-retrieval/src/v2.rs](../../../codex-rs/hepta-memory-retrieval/src/v2.rs). Native hot-path limits now enforce <=512 candidates and <=16 results. Recall risk checks are scoped to the returnable population so a low-ranked tail item cannot poison top-k through OOD/contradiction metadata.
- **State and recovery:** Native receipts bind the supplied candidate set, including omitted candidates, and retain explicit channel/score/generation data. Ranking is stateless; existing hepta-memory SQLite retrieval remains the physical content/index owner.
- **Product composition:** `hepta-agentd::cognitive_context` obtains the bounded candidate window only from the canonical `hepta-memory::CognitiveStore`, intersects it with the exact Lane-C read cut, passes the complete admitted window through `retrieve_v2`, then optionally applies `PinnedCognitiveRanker`. The learned ranker may only permute those admitted items. Response budgeting and final owner-cut revalidation remain downstream.
- **Source tests:** [codex-rs/hepta-memory-retrieval/src/v2_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/v2_tests.rs), [codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs), [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs). The Agentd suite includes deterministic RET-03 coverage that revokes memory after ranking/context assembly but before final publication revalidation. These remain test identities until exact-candidate execution evidence is recorded.
- **Implementation and operating references:** [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md), [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md).
- **Remaining work:** The real SQLite owner/generator is now product-composed for the V2 deterministic bridge, so arbitrary product callers no longer supply the candidate set. Full generation-bound recall is still not composed because the owner does not yet supply the complete `CognitiveSnapshotKeyV1` external generation tuple or native vector/causal/procedural channels. Do not fabricate model/tokenizer/template generations to force that composition. The lexical-only RET-04 baseline now has a deterministic, digest-distinct native identity; measured outcome/resource comparisons for no-intervention/no-recurrence/no-inhibition and independent target-host acceptance remain open.

# memory.retrieval: implementation design

Parent: `docs/modules/memory.retrieval/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: bounded owner-generated V2 product composition, native cue compilation, V2 input binding and generation-bound recall primitives are implemented. The generation-bound/HNMF target and independent acceptance remain open as listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

The native retrieval and generation-bound APIs now enforce <=512 candidates and <=16 returned results. The 4096-node, 32768-synapse, four-settling-step and 64-active-unit ceilings remain design targets because no native graph-settling/HNMF execution currently consumes them. These are still not latency measurements; target-host p99 and source-revalidation cost require execution evidence.

## 6. Concrete verification cases

- RET-01: channel completion order/permutation yields an identical canonical candidate union.
- RET-02: high-risk contradictory support forces abstention/slow path.
- RET-03: revoked/stale source after ranking cannot be attached to a model request.
- RET-04: no-intervention, lexical-only, no-recurrence and no-inhibition baselines measure independent utility and resource cost.

RET-01 and RET-02 have focused native test identities. RET-03 now also has an Agentd product-boundary regression that inserts a committed tombstone after ranking and requires the read to fail closed before context delivery. RET-04 remains an experiment/longitudinal evidence design rather than a repository pass claim. Test source identity is not an executed exact-candidate receipt; independent evidence remains required.

## 7. Integration, rollback and capability ceiling

C1 first changes a bounded read-only ranking/recall decision. Keep complete legal candidates and assignment propensities for causal evaluation. Rollback restores compatible retrieval/engram profiles and rebuilds caches under current tombstones, not old cached answers.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `compile_cue`, `build_candidate_union` and `recall` in [codex-rs/hepta-memory-retrieval/src/generation_bound.rs](../../../codex-rs/hepta-memory-retrieval/src/generation_bound.rs), plus `retrieve_v2` in [codex-rs/hepta-memory-retrieval/src/v2.rs](../../../codex-rs/hepta-memory-retrieval/src/v2.rs).
- **Named product composition:** [codex-rs/hepta-agentd/src/cognitive_context.rs](../../../codex-rs/hepta-agentd/src/cognitive_context.rs) now consumes the real SQLite owner's `observe_memory_retrieval` output, revalidates and intersects it with the coherent Lane C read, binds the complete owner observation through `retrieve_v2`, optionally applies the externally selected learned ranker only as a secondary permutation, then revalidates the exact ranked memory/source/KG bindings and the owner cut before publication.
- **Canonical ranking precedence:** SQLite channel generation/RRF is the owner generator signal; `retrieve_v2` is the mandatory bounded integrity/ranking boundary for this product path; `PinnedCognitiveRanker` may only reorder that admitted <=16 set. The legacy V1 sorter is hidden from generated API documentation and is not an admissible product provenance receipt.
- **State and recovery:** Ranking remains stateless and the existing hepta-memory SQLite retrieval remains the sole physical content/index owner. No second store or index was introduced.
- **Source tests:** [codex-rs/hepta-memory-retrieval/src/v2_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/v2_tests.rs), [codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs), [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs), [codex-rs/hepta-agentd/src/cognitive_context_budget_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_budget_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md), [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md).
- **Remaining work:** The richer generation-bound product path still requires a host-supplied complete `LaneCGenerationVectorV1` and real vector/procedural/contradiction providers before it can replace the bounded owner-V2 composition. HNMF graph expansion/settling is not implemented. RET-04 longitudinal/no-intervention utility evidence, target-host measurements and independent acceptance remain open; do not infer them from repository fixtures.

# memory.retrieval: implementation design

Parent: `docs/modules/memory.retrieval/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: owner-observation product ranking, deterministic cue compilation, V2 input binding and generation-bound recall are implemented; richer target generators/HNMF settling and independent acceptance remain open as listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-memory-retrieval`.
Packages: `MEM-2-RETRIEVAL`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`compile_cue(objective, approved_context, snapshot) -> MemoryCueV1`; `retrieve(cue, channel_budgets) -> CandidateUnion`; `recall(candidates, engram_snapshot, policy) -> RecallPacketV1 | Abstain`. Channels are explicitly lexical, vector, entity, temporal, causal, procedural and contradiction support where implemented. Each returns scoped IDs, source revisions and a score/support receipt, not unrestricted source payload. The current product adapter additionally exposes `rank_owner_candidates(owner_observation) -> OwnerRankReceiptV1`; this binds the canonical SQLite owner's aggregate RRF observation without relabelling that score as a lexical/vector/graph score.

## 3. State records and transaction design

No source-fact writer. A rebuildable query/recall cache binds the full read snapshot key, cue digest, retrieval/encoder profile, source quotas and truncation policy. Engram/synapse generations are supplied as immutable projections. Candidate-set and propensity facts are appended only through learning.ledger's owner port.

## 4. Deterministic algorithm and scheduling

Run bounded channels in parallel; stable-union by exact event revision; deduplicate; apply source/modality quotas and deterministic pre-assignment truncation; expand only a bounded local engram graph; settle at most four steps; apply per-population competition; detect contradictions; calibrate recall/abstain; revalidate exact source support before returning. Vector closeness does not prove truth; incompatible facts are not averaged into a new fact.

Current product precedence is narrower and explicit: `hepta-memory::CognitiveStore::observe_memory_retrieval` is the only physical candidate generator; `memory.retrieval::rank_owner_candidates` validates, binds and deterministically orders its bounded aggregate RRF observation; the optional `PinnedCognitiveRanker` may only permute those admitted results; the selected attachment set is source/citation/KG revalidated again before context publication. Generation-bound recall remains a separate native capability until the owner supplies semantically typed vector/causal/procedural/contradiction channel evidence. Generation-bound OOD/contradiction/channel-coverage abstention is evaluated over the deliverable top-k only; lower-ranked tail entries remain bound by the canonical union digest but cannot poison an unrelated deliverable set.

## 5. Capacity and performance profile

Use HNMF reference ceilings: <=512 candidate events, <=4096 nodes, <=32768 synapses, <=4 settling steps and <=16 returned events, with <=64 active units per population. Report channel omissions, graph expansion, p99 latency and source revalidation cost; no full-store scan or central synchronous RPC.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- RET-01: channel completion order/permutation yields an identical canonical candidate union.
- RET-02: high-risk contradictory support forces abstention/slow path.
- RET-03: revoked/stale source after ranking cannot be attached to a model request. The Agentd test `post_ranking_withdrawal_fails_closed_before_context_delivery` exercises the ranking-to-delivery race seam.
- RET-04: no-intervention, lexical-only, no-recurrence and no-inhibition baselines measure independent utility and resource cost.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

C1 first changes a bounded read-only ranking/recall decision. Keep complete legal candidates and assignment propensities for causal evaluation. Rollback restores compatible retrieval/engram profiles and rebuilds caches under current tombstones, not old cached answers.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `rank_owner_candidates` in [codex-rs/hepta-memory-retrieval/src/owner_rank.rs](../../../codex-rs/hepta-memory-retrieval/src/owner_rank.rs); `compile_cue`, `build_candidate_union` and `recall` in [codex-rs/hepta-memory-retrieval/src/generation_bound.rs](../../../codex-rs/hepta-memory-retrieval/src/generation_bound.rs); `retrieve_v2` in [codex-rs/hepta-memory-retrieval/src/v2.rs](../../../codex-rs/hepta-memory-retrieval/src/v2.rs). The owner-observation ranker is composed by `hepta-agentd::cognitive_context`; generation-bound recall is source-implemented but not yet the product retrieval path.
- **State and recovery:** Ranking is stateless. The existing `hepta-memory` SQLite store remains the physical content/index owner and generates a bounded observation in one read transaction. `OwnerRankReceiptV1` binds the full admitted observation-relative candidate set, aggregate owner score and owner observation/support digest. Agentd resolves content and revalidates the exact selected bindings before publication.
- **Source tests:** [codex-rs/hepta-memory-retrieval/src/owner_rank_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/owner_rank_tests.rs), [codex-rs/hepta-memory-retrieval/src/v2_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/v2_tests.rs), [codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs), [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs), [codex-rs/hepta-agentd/src/cognitive_context_budget_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_budget_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md), [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md).
- **Remaining work:** The real SQLite owner/generator and ranking-to-delivery revalidation are now product-composed for the existing MemoryFts/EntityFts/GraphOneHop/Recency RRF path. Semantically typed vector, causal, procedural and contradiction generators, engram/synapse graph expansion and four-step HNMF settling are still not product implementations. RET-04 longitudinal/ablation outcome evidence, target-host latency measurements and independent acceptance remain open.

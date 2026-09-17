# memory.retrieval: implementation design

Parent: `docs/modules/memory.retrieval/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: owner-backed product retrieval admission, V2 complete-input binding, generation-bound recall V1 and strict recall V2 are implemented. The current product generator is the canonical SQLite owner and exposes Memory FTS, entity FTS, graph one-hop and recency channels. Vector/causal/procedural generation, bounded HNMF settling and independent acceptance remain target capabilities. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-memory-retrieval`.
Packages: `MEM-2-RETRIEVAL`.

Operation signatures below describe the target contract and its current native/product subset. Preserve the existing SQLite owner and APIs; do not create another authority, content/index store or execution spine.

## 2. Public operations and contract details

Target operations are `compile_cue(objective, approved_context, snapshot) -> MemoryCueV1`; `retrieve(cue, channel_budgets) -> CandidateUnion`; `recall(candidates, engram_snapshot, policy) -> RecallPacket | Abstain`.

The current native surfaces are:

- `compile_cue(CueCompileRequestV1) -> MemoryCueV1`, which validates explicit objective/context/snapshot/profile digests without inventing authority;
- `retrieve_product_v1(ProductRetrievalRequestV1) -> ProductRetrievalReceiptV1`, which binds the exact owner observation digest, complete admitted candidate set and product result limit;
- compatibility `retrieve_v2`, which binds the complete caller-supplied candidate set but does not authenticate its producer;
- `build_candidate_union` and compatibility `recall` for generation-bound channel fixtures;
- `recall_v2`, which enforces the product 512-candidate/16-result ceiling and scopes OOD/coverage risk to the potential top-k horizon while still checking contradiction groups touching that horizon against the complete bounded union.

Target channel vocabulary remains lexical, vector, entity, temporal, causal, procedural and contradiction support. The currently composed owner provides Memory FTS, entity FTS, graph one-hop and recency observations. No absent channel is synthesized from another score.

## 3. State records and transaction design

No source-fact writer. The canonical physical content/index owner remains `hepta-memory::CognitiveStore` and `cognitive_1.sqlite3`. `CognitiveStore::observe_memory_retrieval` creates one bounded, digest-bound owner observation in a SQLite read transaction. Product retrieval binds that observation digest and every Lane-C-admitted candidate. Selected `MemoryRevalidationBinding` values are revalidated together in one owner transaction before context attachment, and the complete Lane-C cut is revalidated again before response publication.

A future rebuildable query/recall cache must bind the full read snapshot key, cue digest, retrieval/encoder profile, source quotas and truncation policy. Engram/synapse generations are supplied as immutable projections. Candidate-set and propensity facts are appended only through the learning ledger owner port.

## 4. Deterministic algorithm and scheduling

Current product precedence is normative for the composed read path:

1. The SQLite owner enumerates bounded Memory FTS, entity FTS, graph one-hop and recency candidates and emits its observation digest.
2. The Lane-C read cut admits only exact live record ID, revision and content-digest matches.
3. `memory.retrieval` applies deterministic owner-bound admission under the 512-candidate/16-result product ceiling and emits a complete-input receipt.
4. Selected owner bindings are batch-revalidated in one SQLite transaction.
5. An explicitly configured learned ranker may reorder only that verified admitted set; it cannot resurrect an omitted/stale candidate.
6. The caller applies its smaller response count/byte budget, plans the context, and revalidates the complete Lane-C cut before publication.

The fuller target algorithm remains: run bounded channels in parallel; stable-union by exact event revision; deduplicate; apply source/modality quotas and deterministic pre-assignment truncation; expand only a bounded local engram graph; settle at most four steps; apply per-population competition; detect contradictions; calibrate recall/abstain; revalidate exact source support before returning. Vector closeness does not prove truth; incompatible facts are not averaged into a new fact.

## 5. Capacity and performance profile

Product-facing retrieval and `recall_v2` enforce <=512 candidates and <=16 results. The compatibility V1/V2 sorter retains its historical 16,384/256 bounds only so older native callers and golden digests do not silently change semantics; it is not the product admission API.

The remaining HNMF target ceilings are <=4096 nodes, <=32768 synapses, <=4 settling steps and <=64 active units per population. Report owner channel omissions, product-input omissions, graph expansion, p99 latency and source revalidation cost. No full-store scan or central synchronous RPC.

These ceilings are source-enforced only where named above. HNMF ceilings remain design targets until that execution engine and target-host measurements exist.

## 6. Concrete verification cases

- RET-01: channel completion order/permutation yields an identical canonical candidate union. Native regression: `channel_completion_order_cannot_change_union_or_recall`.
- RET-02: high-risk contradictory support touching a potential selection forces abstention. Native regressions cover V1 contradiction handling and V2 selected-horizon contradiction handling.
- RET-03: revoked/stale source after ranking cannot be attached to a model/context request. The product path batch-revalidates selected owner bindings and then revalidates the complete Lane-C cut; owner tests exercise coherent batch revalidation under a concurrent write. Exact Agentd rank-to-revalidation race injection remains qualification work.
- RET-04: no-intervention, lexical-only, no-recurrence and no-inhibition baselines measure independent utility and resource cost. This remains an experiment/qualification requirement and is not claimed by repository unit tests.

These cases distinguish executable regressions from product/independent evidence. A source test identity is not an execution receipt.

## 7. Integration, rollback and capability ceiling

The existing `hepta-agentd` `CognitiveContext` path is the named product caller for owner-backed retrieval admission. It consumes the canonical SQLite owner observation, intersects it with the coherent Lane-C cut, invokes `retrieve_product_v1`, batch-revalidates selected owner bindings, optionally applies `PinnedCognitiveRanker`, and performs final Lane-C revalidation.

Rollback removes that composition and returns to the predecessor SQLite ranking path without migrating or rewriting owner facts. Compatibility V1/V2 receipts remain decodable; product code must not interpret a V1 receipt as proof of complete input or owner provenance.

Full C1/HNMF activation still requires the actual model-turn consumer/model tuple, missing generator channels, causal outcome capture, independent selection and target-host qualification. Immediate revocation/stop remains effective across frozen snapshots. No generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `compile_cue` in [codex-rs/hepta-memory-retrieval/src/product.rs](../../../codex-rs/hepta-memory-retrieval/src/product.rs); `retrieve_product_v1` in [codex-rs/hepta-memory-retrieval/src/product.rs](../../../codex-rs/hepta-memory-retrieval/src/product.rs); `retrieve_v2` in [codex-rs/hepta-memory-retrieval/src/v2.rs](../../../codex-rs/hepta-memory-retrieval/src/v2.rs); `build_candidate_union` in [codex-rs/hepta-memory-retrieval/src/generation_bound.rs](../../../codex-rs/hepta-memory-retrieval/src/generation_bound.rs); `recall_v2` in [codex-rs/hepta-memory-retrieval/src/recall_v2.rs](../../../codex-rs/hepta-memory-retrieval/src/recall_v2.rs); compatibility `recall` in [codex-rs/hepta-memory-retrieval/src/generation_bound.rs](../../../codex-rs/hepta-memory-retrieval/src/generation_bound.rs).
- **Product callers:** [codex-rs/hepta-agentd/src/cognitive_context.rs](../../../codex-rs/hepta-agentd/src/cognitive_context.rs), function `read`, composes the canonical SQLite owner observation through `retrieve_product_v1` and owner batch/final-cut revalidation.
- **State and recovery:** Native receipts bind supplied candidates; the product receipt additionally binds the owner observation. Ranking remains stateless. The existing `hepta-memory` SQLite database remains the sole physical content/index owner.
- **Source tests:** [codex-rs/hepta-memory-retrieval/src/product_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/product_tests.rs), [codex-rs/hepta-memory-retrieval/src/v2_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/v2_tests.rs), [codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs), [codex-rs/hepta-memory-retrieval/src/recall_v2_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/recall_v2_tests.rs), [codex-rs/hepta-memory/src/cognitive_retrieval_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_retrieval_tests.rs), [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs), [codex-rs/hepta-agentd/src/cognitive_context_budget_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_budget_tests.rs).
- **Implementation and operating references:** [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md), [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md).
- **Remaining work:** The composed owner generator currently supplies four real channels, not the complete target lexical/vector/entity/temporal/causal/procedural/contradiction/HNMF execution model. Vector/causal/procedural generation, calibrated OOD/contradiction production, engram settling, RET-04 longitudinal/ablation evidence, actual model-turn consumption and independent acceptance remain separate work. Do not infer them from an owner-bound RRF observation or caller-supplied generation-bound fixtures.

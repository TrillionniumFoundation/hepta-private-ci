# knowledge.graph: implementation design

Parent: `docs/modules/knowledge.graph/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: complete/incremental generation, publication and bounded relation query kernels implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-kg`.
Packages: `MEM-4-KG`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`consume_source_batch(source_frontier, facts, corrections, tombstones) -> ProjectionCandidate`; `build_generation(candidate, graph_profile) -> GraphGeneration`; `publish_generation(expected_predecessor, validated_generation) -> ProjectionReceipt`; `query_relations(snapshot, seeds, bounds) -> RelationResult`. Supported relation kinds include supports, contradicts, temporal, causal, procedural and prompt-factor interaction, each with explicit source support and validity.

## 3. State records and transaction design

`knowledge_graph_projection` and `prompt_factor_graph_projection` are rebuildable, never source truth. Nodes key entity/fact/factor identity and generation; edges key endpoints+relation+support revision, with confidence, validity, tombstone cutoff and producer profile. Source frontier and complete-generation manifest are published atomically. A partial builder cannot update the selected graph pointer.

## 4. Deterministic algorithm and scheduling

Consume exact source/correction order; remove revoked support; rebuild affected adjacency within the declared bound; retain contradictory alternatives with separate supports; validate no unsupported edge; publish one complete generation. Incremental and full rebuild paths must be observationally equivalent for the same source cut. Prompt-factor complements/substitutes/conflicts are projections of registered facts, not new instruction authority.

## 5. Capacity and performance profile

Pilot per-query expansion <=4096 nodes and <=32768 edges, output <=512 references; builder batches <=10000 source records. Persistent growth is constrained by support retention. Measure incremental rebuild, complete rebuild, generation publication, tombstone propagation and query p99.

The repository PERF-LIBRARY probe now drives 256 real product mutations to 4,096 physical nodes and 32,768 physical edges, then samples product retrieval/GraphOneHop and ordinary reopen while reporting p50/p95/p99, throughput, DB/WAL size, RSS and Linux CPU ticks. This is a CI measurement receipt, not a target-host latency threshold. Full-generation rebuild remains the selected runtime writer until a concrete target-host budget justifies promoting the independently checked incremental path.

## 6. Concrete verification cases

- KG-01: incremental versus full rebuild produces equal semantic graph digests.
- KG-02: deleting the last non-revoked support removes/invalidates the derived edge.
- KG-03: partial generation or mismatched source frontier cannot be selected for reads.
- KG-04: supports and contradicts edges remain distinct and cannot be collapsed into an unsupported high-confidence centroid.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

World-model consumers must distinguish symbolic evidence relations from learned dynamics. `knowledge.graph` owns semantic projection/query rules; `cognitive.store` / `hepta-memory` owns the physical SQLite schema and transaction; cognitive facts and prompt-registry facts remain owned by their source modules. KG reads compose with cognitive snapshots and cannot construct mutation authority. Agentd is the named product host that selects the scoped cognitive mutation feature; ordinary Codex stays default-off. Rollback selects a rebuildable compatible projection after current deletion filtering. Test-only crash rendezvous exercise process death before semantic receipt and after semantic receipt but before current-pointer CAS; reopen must recover the exact predecessor. Product reopen remains bounded to current-state integrity plus the exact predecessor needed by current publication; full historical publication-chain replay is reserved for qualification/forensic audit rather than every startup.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Canonical deterministic core:** `build_complete_generation`, `apply_incremental_delta`, `publish_generation` and `query_relations` are implemented in [codex-rs/hepta-kg/src/generation.rs](../../../codex-rs/hepta-kg/src/generation.rs). V2 preserves canonical/custom relation identity, explicit support lineage, validity windows, exact predecessor publication and generation-bound queries. Query results bind a canonical request digest covering exact seeds, relation filters, temporal cut and edge bound, so a result receipt cannot be replayed as evidence for a different request that happens to return the same edges.
- **Cognitive source adapter and durable owner:** [codex-rs/hepta-memory/src/cognitive_kg_store.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_store.rs) derives V2 nodes/edges/supports from the existing cognitive SQLite facts. `refresh_scope_projection_tx` builds the complete V2 candidate, reconstructs the predecessor, validates `publish_generation`, persists physical projection rows and immutable semantic receipts, and CAS-advances the selected generation inside the same SQLite transaction. It does not create a second fact store.
- **Persisted semantic identity and recovery:** [0013_kg_generation_semantics.sql](../../../codex-rs/hepta-memory/migrations/0013_kg_generation_semantics.sql) stores source-snapshot, generation-vector, graph-profile, generation and publication digests. Reopen recomputes physical input/output truth, reconstructs canonical V2 semantics, and replays predecessor-bound publication; tampered or partial current receipts fail closed. Legacy pre-0011 history cannot drive digest-bound graph expansion without a V2 receipt.
- **Product query consumer:** the GraphOneHop path in [cognitive_retrieval.rs](../../../codex-rs/hepta-memory/src/cognitive_retrieval.rs) reconstructs the persisted V2 generation, fences it by `generation_sha256`, and calls `hepta_kg::query_relations`. Relation selection, temporal visibility and truncation therefore have one semantic owner; SQL only resolves the selected support identities back to physical memory occurrences.
- **Prompt-factor owner source and projection:** [codex-rs/hepta-prompt-registry/src/lib.rs](../../../codex-rs/hepta-prompt-registry/src/lib.rs) owns governed complements/substitutes/conflicts and is the only constructor of the sealed `PromptFactorGraphSourceV1`. [codex-rs/hepta-kg/src/prompt_factor.rs](../../../codex-rs/hepta-kg/src/prompt_factor.rs) rebuilds that exact source into `KnowledgeGenerationV2` with registry-revision support lineage and the registry source digest as the generation source snapshot. Revocation removes non-admitted endpoints/relations on the next rebuild.
- **Prompt-factor real consumer:** [codex-rs/hepta-prompt-optimizer/src/graph.rs](../../../codex-rs/hepta-prompt-optimizer/src/graph.rs) requires every candidate factor to exist in the complete V2 generation and queries the exact generation for complements/substitutes/conflicts. `PromptConflicts` are hard co-selection exclusions and `PromptSubstitutes` are hard redundancy exclusions. `PromptComplements` are counted and request/result-bound but do not add unsupported numeric gain; calibrated complement marginal utility must come from causal interaction evidence. The graph-bound portfolio receipt binds the exact query request digest, query result digest and typed relation counts. The optimizer remains read-only and authority-free.
- **Oracle/product tests:** [cognitive_kg_oracle_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_oracle_tests.rs) compares full and incremental V2 generation with SQLite materialization, reopen, correction/tombstone and query visibility, including physical output, generation and publication digests; it also reconstructs the full persisted predecessor-bound publication chain and verifies fail-closed live entity shape conflicts plus legal shape evolution after correction. [cognitive_store_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_store_tests.rs) adds the ignored child-kill crash-window matrix. [cognitive_kg_benchmark_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_benchmark_tests.rs) emits the PERF-LIBRARY pilot receipt. [cognitive_product_e2e.rs](../../../codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs) exercises the real Agentd/App Server path and checks persisted receipts across restart/correction/forget plus fail-closed startup when the writer store is unavailable. Prompt-stack tests in [prompt registry](../../../codex-rs/hepta-prompt-registry/src/lib_tests.rs), [prompt factor projection](../../../codex-rs/hepta-kg/src/prompt_factor_tests.rs) and [optimizer graph consumer](../../../codex-rs/hepta-prompt-optimizer/src/graph_tests.rs) cover governed relation admission, sealed source production, revocation/rebuild, V2 query and hard-conflict selection.
- **Current claim boundary:** the cognitive **read** product caller is composed and this candidate makes scoped cognitive mutation the default Agentd product profile while ordinary Codex remains default-off. The separate `qualification-cognitive-write` feature only adds the qualification turn-witness seam. The prompt.registry → knowledge.graph → prompt.optimizer relation path is now source-composed as a separate authority-free projection/consumer chain. The candidate writer and prompt-factor chain remain pending current exact-head and deterministic synthetic-merge proof. `apply_incremental_delta` remains an oracle/reference equivalence path rather than the selected runtime writer algorithm. Module-wide `productionImplementation` and `productExecutionProved` remain false until those current execution receipts are green; target-host qualification and independent acceptance remain separate gates.

## 9. Query work and target evidence

The bounded query clones only the returned visible supports. Its diagnostic
`query_relations_with_work` entry reports validation-record counts separately
from selection scans and copies, with exactly the same canonical result as the
ordinary entry. The full generation still needs validation and exact omissions
still require scanning all matching candidates; this change claims bounded
result copying, not constant-time lookup or fully localized writes.

Use [the exact-source target-host procedure](../../knowledge-graph/TARGET_HOST.md)
for workload-bound release measurements and raw logs. CI retains native feedback
after an earlier gate fails without accepting the failed gate. Implemented,
composed, tested, target-measured and independently accepted remain separate.

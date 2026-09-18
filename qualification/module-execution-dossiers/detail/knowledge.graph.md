# knowledge.graph: implementation design

Parent: `docs/modules/knowledge.graph/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: complete/incremental generation, publication and bounded relation query kernels implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Semantic root: `codex-rs/hepta-kg`.
Durable/product composition evidence: `codex-rs/hepta-memory/src/cognitive_kg_store.rs`, `codex-rs/hepta-memory/src/cognitive_retrieval.rs`, migration `0011_kg_kernel_generation_digest.sql`, and the physical Agentd cognitive product test.
Packages: `MEM-4-KG`, with the existing cognitive-store and memory-retrieval owner boundaries retained for their physical files.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`consume_source_batch(source_frontier, facts, corrections, tombstones) -> ProjectionCandidate`; `build_generation(candidate, graph_profile) -> GraphGeneration`; `publish_generation(expected_predecessor, validated_generation) -> ProjectionReceipt`; `query_relations(snapshot, seeds, bounds) -> RelationResult`. Supported relation kinds include supports, contradicts, temporal, causal, procedural and prompt-factor interaction, each with explicit source support and validity.

## 3. State records and transaction design

`knowledge_graph_projection` and `prompt_factor_graph_projection` are rebuildable, never source truth. Nodes key entity/fact/factor identity and generation; edges key endpoints+relation+support revision, with confidence, validity, tombstone cutoff and producer profile. Source frontier and complete-generation manifest are published atomically. A partial builder cannot update the selected graph pointer.

## 4. Deterministic algorithm and scheduling

Consume exact source/correction order; remove revoked support; rebuild affected adjacency within the declared bound; retain contradictory alternatives with separate supports; validate no unsupported edge; publish one complete generation. Incremental and full rebuild paths must be observationally equivalent for the same source cut. Prompt-factor complements/substitutes/conflicts are projections of registered facts, not new instruction authority.

## 5. Capacity and performance profile

Pilot per-query expansion <=4096 nodes and <=32768 edges, output <=512 references; builder batches <=10000 source records. Persistent growth is constrained by support retention. Measure incremental rebuild, complete rebuild, generation publication, tombstone propagation and query p99.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- KG-01: incremental versus full rebuild produces equal semantic graph digests.
- KG-02: deleting the last non-revoked support removes/invalidates the derived edge.
- KG-03: partial generation or mismatched source frontier cannot be selected for reads.
- KG-04: supports and contradicts edges remain distinct and cannot be collapsed into an unsupported high-confidence centroid.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

World-model consumers must distinguish symbolic evidence relations from learned dynamics. KG reads compose with cognitive snapshots and cannot construct the production cognitive writer. Rollback selects a rebuildable compatible projection after current deletion filtering.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Canonical semantic entrypoints:** `build_complete_generation`, `derive_incremental_delta`, `apply_incremental_delta`, `publish_generation`, and `query_relations` in [codex-rs/hepta-kg/src/generation.rs](../../../codex-rs/hepta-kg/src/generation.rs). V2 is the canonical product semantic kernel; the small `rebuild` API in `lib.rs` remains a compatibility surface, not a second product policy.
- **Durable product composition:** [codex-rs/hepta-memory/src/cognitive_kg_store.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_store.rs) translates the exact current SQLite fact cut into `KnowledgeGenerationV2`, validates predecessor-bound publication with `publish_generation`, and writes the generation receipt/nodes/edges plus pointer CAS in the same existing SQLite transaction. It does not create a second fact store or move source-ledger authority.
- **Persisted semantic fence:** migration [0011_kg_kernel_generation_digest.sql](../../../codex-rs/hepta-memory/migrations/0011_kg_kernel_generation_digest.sql) stores the canonical V2 generation digest in each new projection-generation receipt. The pre-existing `output_sha256` remains unchanged for backward readability. Historical rows may have a null kernel digest, but reopen/query reconstructs and validates the V2 generation before use; new rows additionally require exact digest equality.
- **Product query consumer:** [codex-rs/hepta-memory/src/cognitive_retrieval.rs](../../../codex-rs/hepta-memory/src/cognitive_retrieval.rs) routes the `GraphOneHop` channel through `query_relations` bound to the current generation digest, then maps canonical relation identities back to persisted occurrence records for memory retrieval.
- **Relation/support identity:** V2 supports fixed relation kinds plus collision-resistant domain-separated identities for canonical named relations, while SQLite retains the original relation text. Supports carry independent stable support IDs so multiple facts from one source revision remain distinct.
- **Oracle coverage:** [codex-rs/hepta-memory/src/cognitive_kg_store_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_store_tests.rs) contains `sqlite_projection_is_kernel_canonical_across_query_restart_correction_and_tombstone`, covering full build, derived incremental replay, SQLite materialization, product GraphOneHop query, reopen, correction and tombstone equivalence. [codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs](../../../codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs) binds the physical product path to the persisted canonical generation digest. These are test identities until an exact-candidate CI receipt completes.
- **Implementation and operating references:** [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md).
- **Remaining target work:** the memory-backed knowledge-graph path is source-composed by this candidate. Prompt-factor projection composition, measured hot-path optimization/capacity qualification, independent semantic acceptance, activation, promotion and release remain separate. No document may self-certify those gates.

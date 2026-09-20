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

- **Canonical deterministic core:** `build_complete_generation`, `apply_incremental_delta`, `publish_generation` and `query_relations` are implemented in [codex-rs/hepta-kg/src/generation.rs](../../../codex-rs/hepta-kg/src/generation.rs). V2 preserves canonical/custom relation identity, explicit support lineage, validity windows, exact predecessor publication and generation-bound queries.
- **Cognitive source adapter and durable owner:** [codex-rs/hepta-memory/src/cognitive_kg_store.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_store.rs) derives V2 nodes/edges/supports from the existing cognitive SQLite facts. `refresh_scope_projection_tx` builds the complete V2 candidate, reconstructs the predecessor, validates `publish_generation`, persists physical projection rows and immutable semantic receipts, and CAS-advances the selected generation inside the same SQLite transaction. It does not create a second fact store.
- **Persisted semantic identity and recovery:** [0011_kg_generation_semantics.sql](../../../codex-rs/hepta-memory/migrations/0011_kg_generation_semantics.sql) stores source-snapshot, generation-vector, graph-profile, generation and publication digests. Reopen recomputes physical input/output truth, reconstructs canonical V2 semantics, and replays predecessor-bound publication; tampered or partial current receipts fail closed. Legacy pre-0011 history cannot drive digest-bound graph expansion without a V2 receipt.
- **Product query consumer:** the GraphOneHop path in [cognitive_retrieval.rs](../../../codex-rs/hepta-memory/src/cognitive_retrieval.rs) reconstructs the persisted V2 generation, fences it by `generation_sha256`, and calls `hepta_kg::query_relations`. Relation selection, temporal visibility and truncation therefore have one semantic owner; SQL only resolves the selected support identities back to physical memory occurrences.
- **Oracle/product tests:** [cognitive_kg_oracle_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_oracle_tests.rs) compares full and incremental V2 generation with SQLite materialization, reopen, correction/tombstone and query visibility, including physical output, generation and publication digests. [cognitive_product_e2e.rs](../../../codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs) exercises the real Agentd/App Server path under the explicit `qualification-cognitive-write` profile and checks persisted receipts across restart/correction/forget.
- **Current claim boundary:** the cognitive **read** product caller is composed. The cognitive durable writer is exercised only by the explicit qualification profile; default Agentd binaries keep it disabled, so a default production writer is not established. `apply_incremental_delta` remains an oracle/reference equivalence path rather than the selected runtime writer algorithm. The prompt-factor graph projection remains uncomposed. Exact-candidate CI, target-host qualification and independent acceptance remain separate gates.

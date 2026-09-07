# knowledge.graph: implementation design

Parent: `docs/modules/knowledge.graph/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-kg`.
Packages: `MEM-4-KG`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

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

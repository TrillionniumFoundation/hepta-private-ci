# knowledge.graph acceptance extension — 2026-09-28

This candidate closes delivery evidence around the existing indexed-query and durable-owner implementation. It does not add another graph store, replace the selected writer, or grant production acceptance.

## Public query resource contract

`VerifiedKnowledgeGenerationV2` owns one validated immutable generation and derived node, incident-edge and relation indexes. Temporal visibility is evaluated on every request; only structural validation and immutable indexes are reused.

The external entry point is `VerifiedKnowledgeGenerationV2::query_relations_external`. It has a public default budget and a public hard maximum. A caller may lower the per-request support-work budget but cannot raise the library ceiling. Its outcomes are deliberately distinct:

- a successful empty result is `Ok` with no edges and an exact omitted count;
- invalid admission is `KnowledgeQueryAdmissionErrorV2::InvalidBudget`;
- runtime exhaustion is `KnowledgeQueryAdmissionErrorV2::BudgetExceeded`;
- semantic and source-cut failures retain `KnowledgeGenerationErrorV2` inside `Query`;
- no exhausted request returns a partial success.

`query_relations_reference_unbounded` is the explicitly named full-scan oracle operation. It is retained for migration, trusted-owner comparison and equivalence testing; it is not the external resource contract. The older budgeted method remains source-compatible and maps admission/exhaustion to its historical `InvalidQueryLimit` error.

The product call paths are now closed over bounded indexed views rather than the unbounded oracle. Cognitive retrieval retains one verified view per owner SQLite read transaction and uses the library default budget, which is above the composed owner's bounded node/edge occurrence ceiling. `PromptFactorProjectionV1` seals one shared immutable verified view and the optimizer calls `query_relations_external` on that view. Repeated optimizer calls therefore reuse structural validation and indexes, while any temporal cut supplied by a query would still be evaluated per call. The graph-bound optimizer receipt binds both charged support work and the applicable default budget.

`codex-rs/hepta-kg/tests/query_resource_contract.rs` proves that true empty, invalid budget, exhausted budget and explicit unbounded reference execution cannot be confused. The prompt optimizer additionally proves that its real owner projection distinguishes exhaustion from a true empty result. The existing public acceptance matrix continues to compare complete indexed/reference results, including request/result digests and exact omitted counts.

## Publish, crash, recovery and retry consistency

The durable owner keeps source append, memory revision, immutable facts, generation/publication receipts and current-pointer advancement in one SQLite transaction. The candidate now requires three complementary evidence classes:

1. ordinary owner tests for lost source acknowledgement, competing corrections and rollback before publication;
2. `kg_delivery_consistency` public-API tests that reconcile a committed-but-unacknowledged correction after reopen, reject a stale whole-operation retry, and bind the recovered memory head and KG generation digest to the exact successful receipt;
3. the ignored child-process crash matrix at `before_semantic_receipt` and `after_semantic_receipt_before_current_pointer`, followed by reopen and SQLite integrity checking.

Both the exact-candidate runner and the normal knowledge.graph qualification workflow execute the public delivery-consistency integration test. The exact-candidate runner also executes the destructive crash matrix and requires exact non-skipped summaries. A test definition, successful compilation, ignored test, zero-test result or skipped crash scenario is not scenario evidence.

## Long-history concurrency and deletion

`cognitive_kg_benchmark_tests::history::qualification_kg_history_reopen_no_resurrection` overlaps each correction with product retrieval. A reader may observe the complete predecessor or successor, never a mixed memory/KG cut. The probe also checks the latest revision after writer completion and reopen, then verifies across repeated reopens that deletion cannot resurrect.

Writer latency, reader latency and the complete contention round remain separate distributions. None is relabeled as isolated SQLite transaction time.

## Complete-operation measurements

`codex-rs/hepta-kg/tests/operation_measurement.rs` emits `hepta.knowledge-graph-operation-metrics.v2` and separately records:

- input clone;
- complete build/validate/seal;
- bounded generation update;
- verified-view construction;
- first bounded query;
- repeated hot bounded queries;
- explicit unbounded reference query;
- predecessor-bound publication-receipt construction.

The prompt optimizer's product receipt separately binds the actual support-work charge and default budget used by its bounded indexed query. These are regression observations, not host-independent service-level claims. The native SQLite measurement separately records durable mutation, query, reopen, writer, reader and complete contention-round distributions, plus bounded-query work and storage/process observations.

## Exact evidence chain

Every exact candidate lane writes `hepta.knowledge-graph-delivery-evidence.v2`. Each contract row binds:

```
contract → implementation symbol → named test → tested commit/tree
         → runner environment identity → content-addressed evidence file
         → remaining open reason
```

The product execution inventory includes the prompt-optimizer package and retains its native log as content-addressed evidence. The implementation map binds the changed consumer source and named optimizer tests to the exact candidate; the existing evidence validator continues to check `identity.txt`, all required result rows, exact native test summaries, operation metric schema, live Rust/Cargo identity and—on product lanes—the recorded `protoc` identity. Source-head release measurements must bind both the tested commit and tested tree.

The claim boundary keeps these states separate:

- source checks passed;
- native binary compiled;
- query scenario executed;
- recovery scenario executed;
- destructive scenario executed;
- history scenario executed;
- target host qualified;
- independent acceptance;
- activation;
- release.

Hosted lanes may establish only the applicable source, compilation and scenario states. They do not establish operator target-host qualification, independent acceptance, activation or release.

## Remaining acceptance boundary

`revision_facts_v1` remains compact persistent representation, not an incremental-runtime claim. Complete bounded rebuild remains the selected writer until a separately reviewed design proves correction, deletion, lineage, crash and recovery parity and wins a predeclared comparison on a named target CPU/storage profile.

The implementation and tests in this document are not themselves successful execution receipts. The PR remains a candidate until the exact commit has produced complete passing artifacts for all required lanes.

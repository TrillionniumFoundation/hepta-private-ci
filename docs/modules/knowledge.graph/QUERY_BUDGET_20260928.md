# Indexed query resource contract and candidate closure

Date: 2026-09-28. Module: `knowledge.graph`.
Parent: [TECHNICAL.md](TECHNICAL.md).
This document describes implemented candidate source, not an execution or acceptance receipt.

## Source and authority boundary

`VerifiedKnowledgeGenerationV2` owns an immutable validated generation. Its node map, relation inventory and adjacency are derived indexes, never source truth. Owners must still bind the view to the exact read transaction/source cut and retain their authorization, owner, scope and epoch fences.

Structural validation and index construction occur once per owned immutable view. Query-time temporal visibility is recomputed for every call and is not cached as a permanent conclusion.

## External bounded entry

The public constants are:

- `DEFAULT_QUERY_SUPPORT_WORK_V2 = 1_000_000`;
- `MAX_QUERY_SUPPORT_WORK_V2 = 1_000_000`.

`query_relations_external(query, requested_budget)` uses the default when `requested_budget` is `None`. A positive caller budget may be lower than the default but may not exceed the hard maximum.

One support-work unit is one endpoint support inspected, one edge support inspected, or one retained support copied. Charging occurs before the corresponding work. Structural queries are charged for retained support copies even when no clock visibility check is needed. Expired endpoint scans and omitted-edge visibility checks also consume work; a small output edge limit cannot hide the work needed for an exact omitted count.

Outcomes are explicit:

- `Ok(result, work)` is a complete result; an empty edge list is a genuine successful empty result;
- `InvalidBudget` means the request was not admitted;
- `BudgetExceeded` means the complete scan could not be finished within the admitted budget;
- `Query(error)` preserves semantic, digest and source-cut failures.

Exhaustion never returns a truncated successful result, never claims an exact omitted count for unfinished work, never mutates the generation and does not poison later requests.

The source-compatible `query_relations_with_work_budget` retains its historical `InvalidQueryLimit` mapping. New external callers should use the explicit admission type. `query_relations_reference_unbounded` is the deliberately named full-scan oracle operation for trusted migration/equivalence work; it is not an external request path.

## Other costs and limits

Generation validation and index construction are separate from per-query support work. The immutable incident index is bounded by the validated kernel edge limit; each edge is indexed at most twice and a self-loop once. Query input lengths and output edge counts retain their existing hard limits.

The diagnostic work counters are operation accounting, not byte-perfect allocator/RSS or latency metrics. Actual peak RSS, database/WAL growth, elapsed times and contention require native measurement.

The cognitive owner still rebuilds one complete bounded canonical generation per logical mutation. `revision_facts_v1` avoids a complete physical node/edge copy for every generation, but does not claim incremental computation. Publication remains predecessor-bound and current-pointer advancement remains in the same SQLite transaction.

## Regression and acceptance evidence

`codex-rs/hepta-kg/tests/query_resource_contract.rs` distinguishes successful empty, invalid budget, exhausted budget and explicit unbounded reference execution. `query_acceptance.rs` retains indexed/reference result equivalence across structural and temporal cuts, seed permutations, relation filters, edge limits, self-loops, duplicate support identity, withdrawal and source-cut mismatch.

`operation_measurement.rs` records cold bounded query, repeated hot bounded query, explicit unbounded reference query, verified-view construction, complete build/validate/seal, generation update and publication-receipt construction separately.

All exact-candidate lanes must bind their named tests, tested commit/tree, environment identity and content-addressed evidence files. Hosted measurements remain regression evidence rather than target-host acceptance. No production, independent acceptance, activation or release flag is advanced by this contract.

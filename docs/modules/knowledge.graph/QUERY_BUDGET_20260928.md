# Indexed query resource contract and candidate closure

Date: 2026-09-28. Module: `knowledge.graph`.
Parent: [TECHNICAL.md](TECHNICAL.md).
This document describes implemented candidate source, not an execution or acceptance receipt.

## Source and candidate identity

The continuation branch is `work/kg-abc-closure-20260928`, stacked on
`c889adf8a1129b7c45a1c4edb87e69dc83387b83` from
`work/kg-abc-execution-20260927`. The qualification baseline remains the exact main
object `a126987b84737dbc2ee2592442a314117bddb4a2`, not a moving `main` reference.
PR #1142 isolates the continuation changes. Existing verified-generation,
transaction-local caching, support-identity validation and history-measurement code
are inherited work, not newly claimed work in this continuation.

The preparation job may make ordinary, inspectable formatting/document-link commits
and then a map-only source-binding commit on this branch. Each execution job checks
out the resulting immutable candidate. Preparation is not test success. Execution
must not edit tracked source. Neither map rebinding nor a successful digest check
changes production, product-execution, acceptance, activation or release flags.

## Query-local support work

`VerifiedKnowledgeGenerationV2` owns an immutable, validated generation. Its node
index, relation inventory and adjacency are derived indexes, not source truth.
Queries still require the exact generation digest. The owner must retain its existing
owner/scope/transaction fences; an old sealed view is not evidence of current source
truth or authorization.

`query_relations_with_work_budget(query, maximum_support_work)` admits a positive
caller budget of at most **1,000,000 support-work units**. The existing
`query_relations` and `query_relations_with_work` methods use this ceiling. A unit is
one endpoint support inspected, one edge support inspected, or one retained support
copied. The implementation charges before the corresponding inspection or copy.
Structural queries are charged for copied supports even though they perform no
clock visibility inspection. Expired endpoint scans and omitted-edge visibility
checks also consume budget; a small edge output limit cannot hide this work.

An invalid or exhausted budget returns `KnowledgeGenerationErrorV2::InvalidQueryLimit`.
It does not return a partial successful result, claim an exact omitted count for an
unfinished scan, mutate the generation or poison the next request. Budgets may be
lowered per request but cannot raise the library ceiling. They do not grant authority.

This ceiling does not tighten the composed cognitive owner's 10,000 node-occurrence
and 50,000 edge-occurrence source limits: one indexed temporal query visits each
relevant endpoint at most once and each incident edge once, and retains at most the
original edge supports. For broader direct kernel users the new ceiling is an
explicit resource-admission limit. Successful requests retain the reference result,
request digest, result digest, stable edge order and exact omitted count. A request
that exceeds the budget must be explicitly narrowed by the caller; the library does
not silently omit supports or reduce correctness requirements.

## Other costs and limits

Generation validation and index construction are separate from query selection and
are not charged to this per-query support budget. They must occur once per owned
read-transaction/source-cut cache entry, not once per seed. The incident-index set is
bounded by the validated kernel edge limit, 262,144; adjacency collection visits an
edge at most twice, and self-loops are indexed once. Query input lengths retain their
existing hard limits. A query with many incident edges still scans those matches to
produce an exact omitted count. No constant-time or host-independent latency claim
is made.

The diagnostic counters report inspection and retained-copy counts; for an accepted
indexed query the charged support work is the sum of
`visibility_supports_inspected`, `relation_supports_inspected` and
`selected_supports_cloned`. Validation counters remain zero for an already verified
view. This is operation accounting, not a byte-perfect allocator/RSS metric. Actual
peak RSS, database/WAL growth, elapsed times and contention require native measurement.

## Source consistency and persistence

The cognitive writer still recalculates a complete bounded canonical generation on
each logical mutation. `revision_facts_v1` is compact persistence, not an incremental
computation claim: immutable revision facts and generation receipts reconstruct a
source cut instead of storing a new complete physical node/edge copy every time.
Publication remains predecessor-bound and current-pointer advancement remains in the
same SQLite transaction. The independent full-scan/reference query is retained for
oracle comparisons. See [writer selection](../../../qualification/knowledge-graph/WRITER_SELECTION.md).

## Added native regressions

`codex-rs/hepta-kg/src/indexed_query_budget_tests.rs` exercises reference equality
across structural/time-scoped queries, inclusive/exclusive visibility boundaries,
self-loops, multi-seed deduplication and edge limits. It checks exact support-budget
boundaries and one-unit-under rejection; omitted edges must not clone retained payload.
Other cases verify a failed request does not poison subsequent queries, a caller cannot
raise the ceiling, time is reevaluated on every call, other source cuts are rejected,
and digest tampering, duplicate support identity and tombstones fail closed.

The duplicate-identity regression deliberately recomputes the public object's digest
after introducing two supports with the same `(source_id, source_revision)` but
different fact digests. This tests the semantic validator rather than merely relying
on a stale-digest rejection or constructing all objects through the trusted builder.

## Acceptance evidence

All four exact-candidate lanes remain required: kernel/source-head,
kernel/base-merge, product/source-head and product/base-merge. Required native checks
include formatting, strict Clippy, kernel/prompt tests, cognitive-owner tests,
explicit ignored crash and history/reopen tests, and both ordinary and qualification
Agentd product profiles. The inventory auditor must reject absent, skipped, zero-test
or failed required executions. Logs and tested commit/tree identities are retained.

Release-mode hosted-runner measurements and the hosted regression budget are useful
but are not deployment-host acceptance. Operator-selected CPU/storage/runtime profiles,
long-history workload shape, independent acceptance and release remain separate gates.
No production or release flag is changed by this patch or by this document.

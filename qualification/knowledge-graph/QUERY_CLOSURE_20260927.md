# knowledge.graph query closure — 2026-09-27

Historical candidate design. The published final-convergence staging branch did
not compile or call the indexed view and history test described below. The
2026-10-01 audit materializes those paths and supersedes completion claims here;
see [AUDIT_20261001.md](AUDIT_20261001.md). This document is not an execution receipt.

## Candidate identity and scope

Integration base: `a126987b84737dbc2ee2592442a314117bddb4a2`.
Reviewed reusable KG changes: `ac294a5d0b33794dd8bf85fc252faa5f4df41abd`.
Candidate branch: `work/kg-verified-query-closure-20260927`.

Only the eight KG files changed by the reusable patch are imported after verifying
that they are unchanged between its merge base and the selected main. No other
module's branch is merged or overwritten. The final source is committed before
its implementation map is rebound; the later map commit binds the preceding
source commit/tree plus current path objects without self-referential SHA claims.
The materialization workflow is not a test receipt and deletes its write-enabled
workflow and one-shot patch helper from the finished candidate.

## Implemented changes

- A sealed, owned `VerifiedKnowledgeGenerationV2` validates once and indexes
  incident edges, retaining canonical reference ordering. No unchecked or mutable
  generation access is exposed. This is not proof of current source authority.
- Cognitive retrieval caches the verified generation, relation-kind inventory and
  compact edge-support mapping per scope/generation inside one owner's SQLite
  transaction. No cache or visibility decision survives requests/reopen.
- Indexed selection clones only returned supports and preserves exact omitted
  counts. The full-scan implementation is retained as a differential oracle.
- Builder and validator both reject duplicate support identity even when payload
  differs. Public validation rejects noncanonical node/edge order with recomputed
  digests. Joint endpoint/final-edge revocation is a valid complete source cut.
- A bounded history probe repeatedly corrects one memory, reopens at growing
  historical frontiers, checks exact current revisions, then forgets and reopens
  three times. A post-tombstone correction must fail without advancing generation.
- Malformed benchmark environment values fail rather than silently selecting a
  different fixture. The target receipt parser no longer accepts bool as int.

## Capacity and work accounting

| Layer | Limit and meaning |
| --- | --- |
| Pilot design | 4,096 nodes / 32,768 edges expanded, up to 512 references; not a universal latency SLO |
| Cognitive scope | 10,000 current heads, 10,000 physical node occurrences, 50,000 edge occurrences |
| Kernel generation | 65,536 canonical nodes, 262,144 canonical edges, 50,000 supports per node/edge |
| Cognitive retrieval | 32 channel candidates, 4 final results |
| Indexed query | At most the union of seed-incident canonical edges is visited; duplicates/self-loops are visited once |
| Output copying | Only selected live supports are cloned; exact omission counting may still inspect nonreturned matches |
| History probe | Default 128 corrections, configurable 1–4,096; finite probe, not an indefinite soak |

The aggregate support/byte cost still depends on the admitted source graph. An
edge-count output limit must not be described as a byte or latency budget. A
prepared view moves whole-generation validation/index construction to preparation;
first-request preparation is still real work and must remain in product timings.

## Algorithm and storage decision

Retain complete canonical rebuild as the durable writer. `revision_facts_v1`
reduces persistent duplication; it does not make computation incremental. Promote
an incremental writer only after the same source cut produces identical canonical
and publication digests under correction/deletion/crash tests AND target-host
measurements demonstrate a useful improvement. No unsupported promotion here.

## Required executable evidence

1. Exact source-head and deterministic merge against the fixed main baseline.
2. KG formatting, strict Clippy, kernel tests including query closure differential
   tests; prompt registry/optimizer tests; full cognitive owner library tests.
3. Explicit ignored child-kill transaction-window tests and the explicit history
   probe; ordinary default Agentd and qualification-witness product E2E.
4. PERF-LIBRARY capacity/contention probe, with source/tree, fixture parameters,
   CPU/runtime/storage identity, raw logs and observed percentiles retained.
5. A registered target-host budget evaluated on that actual host. Hosted CI is not
   evidence of a user's target CPU/storage, even when a profile string is supplied.

Check the actual job conclusions and test counts for the FINAL candidate SHA.
Queued, action-required, skipped, zero-selected-test and historical green results
are not current success. A library-only result is not Agentd product execution.
The implementation map's production, execution, acceptance, activation and release
claims remain false unless the corresponding separate evidence is complete.

## Operational checks

Observe preparation count, support-index load count, incident edge visits, support
inspections/copies, correction/query/reopen latency, DB/WAL growth and RSS. Review
high-degree/high-support graphs independently of sparse adjacency tests. Preserve
owner current-source filtering and transaction fencing when optimizing any cache.
An old valid generation or restored old database is not made current by a hash.
External anti-rollback and descriptor-safe writer recovery remain cognitive.store
responsibilities, not guarantees minted by this query cache.

# knowledge.graph continuation audit, 2026-10-02

## Candidate and scope

This continuation starts from draft PR 1314's independently fetched head
`ad0ff102422a64f947763156ca68935f218010c4`, on its own worktree. It does not merge
cognitive.read, prompt.registry, runtime or inference candidates into this branch.
The technical guide, complete graph kernel, prompt-factor adapter, prior audit,
source inventory and cognitive query/generation boundaries inform the review.

## Reproduced ingress defect

Complete-generation canonicalization checked duplicate node and edge identities
only after pruning empty or wholly tombstoned support sets. Consequently, a live
record and a dead record with the same identity were accepted together instead
of rejecting an ambiguous source cut. The full-input uniqueness contract was
inconsistent with support identity validation and incremental delta admission,
which already reject duplicate identities before pruning.

Two regression tests failed on the exact baseline. Each repaired test checks
empty and tombstoned variants in both input orders. The repair retains a bounded
set of seen ingress identities before support pruning, and continues dropping
unique unsupported records as before. It changes no authority, digest format,
source ownership, publication sequence, temporal visibility or public type.

## Verification and further review

The complete KG package passed 35 tests after the repair, including the two new
regressions and existing full/incremental, restored-generation, query-bound,
publication and sealed prompt-source cases. Baseline failures and successful
repair logs are retained separately. These are scoped local package results,
not complete candidate or synthetic-merge execution receipts.

The subsequent review checked aggregate/per-record support bounds before copies,
canonical support conflict detection and order, delta retention/removal identity,
publication predecessor binding, temporal endpoint/edge visibility, query
request/result digests, immutable validated-generation access, registry source
seals, canonical relation uniqueness, and per-transaction cognitive generation
cache keys and persisted digest fences. No additional reproducible actionable
issue was identified within those inspected boundaries. This is a scoped
negative result, not proof of permanent absence of defects or global optimality.

The original candidate's product EPERM failures, mixed-host capacity observations,
source/merge qualification gaps, and independent acceptance/activation/release
requirements remain outstanding. No graph capacity or positive physical-product
result is renewed by this small kernel repair.

Prompt registry/optimizer downstream packages passed 106 tests. Independent
review inspected the identity-before-pruning change and reran the complete KG
package: 35 passed. Scoped `just fix`, strict all-target KG Clippy (`-D warnings`)
and repository `just fmt` passed. No Rust tests were rerun after final fix/format.

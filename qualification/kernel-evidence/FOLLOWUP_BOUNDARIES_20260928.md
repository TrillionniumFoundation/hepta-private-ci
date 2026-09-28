# kernel.evidence boundary follow-up — 2026-09-28

## Scope and exact input

This patch is based on `8657079da6377f4012d73b18d194f75bd3a115f5` of
`fix/kernel-evidence-production-closure` (PR #1092), with observed main
`a126987b84737dbc2ee2592442a314117bddb4a2`. It is an incremental follow-up,
not the original implementation of phases A–C. The upstream three-role solver,
sealed trust, authenticated snapshot, publication state machine, product
composition, backup/build checks and segmented backend remain inherited work.

The scope preserves the upstream payload-digest paging fix and its tests. It
adds a common full-row decoder rather than maintaining a weaker second decoder.
No workflow, release policy, required check, production activation or independent
acceptance is relaxed or granted by this patch.

## Direct source changes

1. Validate the durable accepted trust generation/digest within the same SQLite
   transaction as qualification append or verification. A restored owner file is
   not by itself a monotonic trust oracle. Development before the first accepted
   production generation remains available; accepted production trust cannot be
   replaced by a legacy or unmatched snapshot.
2. Route page rows through the full canonical/provenance-aware row decoder.
   Validate cursor membership against candidate, source commit/tree and claim
   inside one read transaction. Check envelope byte bounds before materializing
   rows. Pagination remains a live append-only traversal, not a fixed historical
   multi-page snapshot proof.
3. Bound Agentd pages to 32 references, accounting for worst-case stable IDs,
   digests, timestamps, predecessor/target IDs and the escaped JSON response.
   This narrows the previous 128-reference maximum; callers must follow pages
   instead of relying on a response that can overflow the 48 KiB frame.
4. Do not classify an acknowledged batch as current external proof when latest
   is missing, different, or unproved. Check batch/store ownership and exact
   updated batch/intent counts before committing a local publication ACK.
   On mismatch, frontier acceptance and batch/intent mutations roll back together.
5. Correct positive production trust fixtures to canonical registry V2; retain
   an explicit negative test proving a matching digest does not admit legacy V1.
6. Apply the observed exact-source rustfmt suggestions and make one explicit
   error-type annotation in the provenance decoder. New semantic Rust changes
   still require native rustfmt, compiler, strict lint and test execution.

The delivery helper also adds the missing `libc` dependency edge to the
`codex-hepta-evidence` and `codex-hepta-agentd` Cargo.lock stanzas. It requires the
inspected full lock blob `cd6650b68a815d69038166b7de50c2857f358641`, changes no
package version/source/checksum, and never removes `--locked`. This narrow
correction does not claim a successful full Cargo dependency resolution.

## Evidence and limits

The formatter artifact from source `815110ed7ff046daf3812e73fb2a9325cbaa0442`
provided formatted bytes for 57 files. Reversing its patch reproduced the Git
blob identities in the patch; all artifact SHA256SUMS were checked. Upstream
comparison to the chosen base changed only a maintenance workflow and paging
source/tests; the paging source baseline was independently matched to blob
`ec3003486fbe6bb47873013c205efc88fe2c982f` before preparing this patch.

At the observed 815110ed source, native diagnostics were blocked at Cargo's
`--locked` preflight; formatting also failed. They are not native pass evidence
for that source, for the newer 8657079d source, or for this follow-up.

The accompanying delivery contains runnable Rust regression tests and separate
Python/SQLite/source-wiring models. The local models execute 24,576 bounded
role-assignment/oracle comparisons and exercise the literal guarded SQL,
transaction rollback and wire budgets. They are NOT compiled Rust tests. No
Rust compiler/toolchain or complete repository build was available in the
patch-building environment. No remote push succeeded from that environment.

## Remaining acceptance work

- Run the same final source and deterministic fixed-main merge through native
  formatting, locked resolution, strict lint, tests, builds and governed CI.
- Synchronize and validate current source inventories, implementation-map and
  status projections against that actual resulting object. Provenance anchors
  may remain historical, but cannot transfer execution evidence to new source.
- Execute real crash/restart, wrong-trust restore, byte/provenance corruption,
  cross-process publication, lost ACK, target-host storage and backup drills.
- Establish whether fixed historical multi-page proofs are required by product
  consumers; the live cursor interface does not claim this property.
- Obtain actual independent signer/operator/reviewer, capacity/RPO/RTO, canary
  and release evidence through the existing respective authorities.

Exact-source qualification, merge qualification, independent acceptance,
production activation and release remain unproved. This document is an
implementation/diagnostic follow-up, not a qualification receipt.

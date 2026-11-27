# Framework implementation verification record

## Current implementation candidates

- Common candidate [#6057](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6057): source `4f7f0f4ef686e71353a5a3a9725c01f3dbffbc50`, tree `d9bed510c731b3afa501daf666b55106b8fb6136`.
- Typed evaluation uncertainty [#6047](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6047): corrected source `ea4b1e0452adb10c8cb0b7eae2ba1754689d11c6`, tree `e4081d0b53867dbefbb662190a956c8cca1d7b14`.
- Resident reuse [#6060](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6060): source `4ae6bbe94ef5be31401ac31b4a6fdeb5128d548f`.
- Windows containment [#6038](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6038): separate source `c53434a799760fbae62e5ee649eb73320032d5bc`, based on `ceadcb3b11dbd94a9d07afb7e6301555e4ff3f80`.

The full implementation and unfinished production-assembly contract is in the
[fixed common-source record](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4f7f0f4ef686e71353a5a3a9725c01f3dbffbc50/qualification/framework-refactor-20261112-8166/README.md).
All candidates remain Draft. This evidence branch does not change implementation source.

## Local source checks after executor recovery

[git-merge-tree.json](git-merge-tree.json) records all six actual local two-parent
`git merge-tree --write-tree` commands. Every result has exit zero and exactly
reproduces the published merge tree. The record binds the current common source
and tree, Git version and observation time.

[local-source-checks.json](local-source-checks.json) preserves the source diff
check, original caller scanner self-test and one original generic-control test
covering five negative mutations. These passed on the current common source.
Initial complete-caller/test attempts failed because the sparse worktree omitted
the tracked CALLERS manifest; those environment observations are retained.
The exact tracked manifest was then materialized and the negative-control test
passed. At the recorded snapshot, the full caller scan had no terminal result;
no full-caller pass is claimed.

Cargo, rustc, rustfmt and just are absent from the restored executor. These are
source checks, not Rust compilation, formatting or native behavior qualification.

## Original evaluation portability failure

[The qualification record](../framework-evaluation-uncertainty-20261112-8166/qualification.json)
binds Windows security-only run 43128124820/job130885288509 to its actual exact
checkout `98730dda67417a93689835f4961d3e807abf107d`.
The complete decoded job log is retained at
[raw/job-130885288509.log](../framework-evaluation-uncertainty-20261112-8166/raw/job-130885288509.log).

Four E0433 errors came from two added readback assertion blocks referencing the
original Linux-only Q24 receipt owner and classifier. This was a new test
portability defect. Corrected source ea4b1e04 applies the same Linux cfg only to
those added blocks. Original cross-platform pending/missing typed readback,
call-count, anchor and holdout checks remain active. The manual long-line wrap is
not an observed formatter pass. The correction still needs its own native result.

This compilation failure is separate from the original Windows elevated
outside-root deletion observation and its containment candidate.

## Native status and retained input qualifications

At 2026-11-12 01:21:28 UTC:

- Common-source runs had been admitted but no current-source native pass was
  observed. Daemon: 43132900164; Cell native: 43132893253; inference: 43132893251.
- Resident native run 43130589962 remained in progress on exact 4ae6bbe9.
- Windows original regressions run 43131094976 remained in progress on exact
  c53434a7. Functional Windows isolation P0 remains open.
- The old evaluation daemon run 43128124778 remained in progress on 98730dda.
  Its eventual results cannot automatically qualify ea4b1e04 or the common source.

The existing [generation evidence](../framework-generation-staging-20261112-8166/README.md)
retains the exact 21d2699b native 96 passed / 0 failed / 1 skipped qualification,
and the previous overall formatting failure. Handoff source 086cc7d2 has the
original daemon ordinary 1235/0/78 and exact UID0 Root 12/12 results, plus a
separate overlapping Shared Cell 1269/0/77 result, linked in #6035.
Do not add overlapping suites or transfer their results to successor sources.

Ordinary complete Adopt, correct NoUpdate and full daemon/Root cold-restart
acceptance remain zero. A durable original Decision producer, post-A late
assembly, independent Outcome and Dataset-cut inputs, actual Root CURRENT service,
distinct B/C custody, global fair microbatching and full physical cost metering
remain unfinished production work.

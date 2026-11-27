# Accepted learning handoff survives response-waiter loss

This checkpoint integrates ordinary branch
`codex/framework-learning-handoff-20261112-8166` at
`307dced98e8b40c1e8321a357e1af1cde3400fef`, including its preceding commit
`086cc7d21bb958c348e352395f0355793ba2de94`.

## Behavior and review

Once the durable outbox claim has been accepted and its reserved command has
entered the owner queue, dropping the response waiter must not discard the
accepted submission before a checkpoint is created. The owner now continues
such submissions. A readback whose waiter has gone away can still be skipped.
The existing supervisor cancellation token, authorization checks, and absolute
work deadline retain control of execution. Both owner selection points give an
already-ready cancellation priority.

The four added regressions use the existing SQLite and actor paths with
explicit fixture stage observations. They cover waiter loss and reconciliation
without duplicate work, cancellation before owner work starts, cancellation
after checkpoint creation followed by recovery, and expired accepted work that
must not start a stage or create a checkpoint. This repairs actor ownership of
accepted work; it does not establish atomicity across a process crash between a
database claim and queue insertion.

Independent source review found that the incoming tests used thirteen fixture
calls whose current helpers now return `Result`. The original unadapted attempt
was retained as a compilation failure, exit 101. The compatibility change adds
error propagation and successful return values to the four tests. It preserves
their order, deadlines, assertions, and awaited checks; it adds no production
behavior.

## Native qualification

| Stage                                                            | Recorded outcome                                                                                                                                                                     |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Original unadapted tests                                         | Compilation failed; no behavioral test pass is claimed.                                                                                                                              |
| Adapted new tests against the original production implementation | All four selected cases failed in the recorded control run, with zero retries.                                                                                                       |
| Actual merged production implementation and adapted tests        | All 165 cases selected by the original `test(learning_iteration)` project filter passed, with zero retries.                                                                          |
| Original complete caller verifier                                | Passed: 7,874 Rust files, 1,645 boundaries, 820 protected boundaries.                                                                                                                |
| Maintenance after testing                                        | `just fmt --base 342b284c1514da3d3d8b6451b6bd3fb6edfc783a` completed successfully. Only one new test function's opening brace moved to the next line. No tests ran after formatting. |

The unchanged caller allowlist and production bytes were checked before and
after qualification. The source-closure review follows all six existing module
inclusion layers to the four new tests, verifies the existing Bazel source glob
and `anyhow` dependency, and retains the original protected markers. It adds no
new build rule, source root, or include/resource reader.

## Actual merge and source binding

The initial real merge is `7277a9f43f9dded6ba7997dfa265da40022d96ba`, with
parents `342b284c1514da3d3d8b6451b6bd3fb6edfc783a` and the original incoming tip.
After the fixture compatibility and formatting steps, the qualified source is
`31b56711b5d755777d16130d0351d0b562d5159b`.

Default three-way merges of that source into both published parent `770179d`
and the independently reviewed AuthBus merge produce the same tree,
`1083ce24a1a673f2a76bee463cf2802b0a130816`, with zero conflicts and exactly three
learning paths changed. The two existing learning blobs are identical in the
native base and these integration parents. `qualified-join-proof.json` and
`verification.json` bind every final path to its Git blob and SHA-256.

The complete evidence archive preserves 92 regular files: original compilation
failure, behavioral control, successful native logs, complete caller result,
source snapshots, exact requests and terminal records, module-closure review,
formatting difference, and real merge proofs. Its original member bytes and
complete membership were verified again when preparing this checkpoint.

These native results are component qualifications at the recorded source. The
combined commit still requires its own hosted checks. The separate refreshed
branch-boundary evidence records the latest HIA exclusions; no HIA parent is
introduced by this learning merge.

## Subsequent scoped Clippy maintenance

The recorded follow-up ran `just fix --offline --locked -p codex-hepta-agentd`
and then `just fmt --base 342b284c1514da3d3d8b6451b6bd3fb6edfc783a` in the
same isolated native source. Both exited successfully. All 1,622 package Rust
files are byte-identical before fixing, after fixing, and after formatting.
The five caller/dependency manifests are unchanged and match the publishing
parent; all three learning source hashes match the qualified final postimages.
No tests ran after this maintenance.

The ten-member original archive retains the complete 222,356-byte Clippy
stderr, all command results and full three-stage hash maps. The separate
thirteen-member control archive preserves exact requests, receipts, terminal
job state and version-pinned download evidence. Root independently verified
every member and the complete source and manifest equality claims.

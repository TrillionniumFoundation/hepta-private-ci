# CognitiveStore first-creation crash recovery: red/green qualification

This package retains the complete negative baseline, the same frozen tests with the 22-line initializer repair, the affected-crate run, and the subsequent final tooling. It establishes a narrow initial-creation permission repair under the recorded Linux conditions. It does not close the eight memory research gates or qualify a production authority provider.

## Actual executions

| Stage | Result | Test time | Wrapper wall time |
| --- | --- | ---: | ---: |
| Original initializer, new regression tests | 2 unique tests: 1 passed, 1 failed; failed test retried once and failed again; 285 filtered/skipped | 0.871 s | 260.679474439 s |
| 22-line repair, identical regression tests | 2/2 passed; 285 filtered/skipped | 0.978 s | 37.892922698 s |
| Entire `codex-hepta-memory` crate | 280/280 passed; 7 skipped | 15.593 s | 17.774360770 s |
| Scoped `just fix` | Exit 0; 19 warnings; no source changes | — | 132.890276143 s |
| Scoped `just fmt` after explicit discard edit | Exit 0; only the new test file changed formatting | — | 0.316039734 s |

The retry is another attempt of the same test. Across the two new regression definitions, this package retains seven actual attempts and fourteen writer/recovery child-process receipts. These are not fourteen independent tasks, and they do not enumerate every subprocess started by the rest of the memory crate. No pretrained model or new training run belongs to this repair cycle.

## What the negative baseline proves

Both initial-generation attempts recorded the writer's and recovery child's actual `Umask: 0022`. The writer exited with code 73 without running Rust destructors, after synchronizing the full external cut. The original main database was `0600`; WAL and SHM were `0644`. Both fresh recovery children exited 101 at the unchanged strict recovery call with `Indeterminate("SQLite recovery is indeterminate: the complete immutable file identity was not established")`. The parent preserved source-after evidence before asserting that failure. All original source bytes and recorded metadata remained unchanged. The already-recovered generation passed with `0600` main/WAL/SHM under the same recorded mask.

The complete baseline-to-green source inventories differ only in `cognitive_store.rs`: a missing main file is exclusively created and protected on its new descriptor before SQLx can create sidecars. All regression source bytes are identical. Green and affected-crate runs pass both initial and recovered generation cases, retain `0600` original bundles, recover the complete external cut, and commit a new write that survives close/reopen. The affected-crate run adds only the workflow's evidence-retention export beyond the green source snapshot.

## Final source bridge and proof boundaries

All three test runs qualify the frozen 319-line test source, SHA `216e074038a5ecf19696ce9e43c6fbf8de78e711c8ae8ee85906b206127f32fe`. `just fix` did not apply the `TempDir::keep` suggestion. The separately recorded edit changes exactly one `temp.keep();` to `let _ = temp.keep();`; final formatting produces the 333-line source SHA `4e428fb4876ad2f833713558cad601a9ac73a9e871824528d27b3b8158f8b88e`. The initializer, module hook and workflow bytes remain those qualified in the affected-crate run. The final four-file source adds 360 lines and removes none.

A full source-map and literal/token review found only the explicit discard plus formatting and an optional comma in an existing two-element tuple. No assertion, timeout, model recipe, authority fixture or recovery gate changed. Final tool receipts preserve all warnings; this is not a warning-free claim. No same-cycle local tests ran after the final tools. Independent final-head CI is separate evidence; an earlier `33c` CI result is not assigned to this repair.

`process::exit(73)` is abrupt process termination, not physical power loss. Crash-time WAL frames exist, but this does not prove the last cut exists exclusively in WAL. The auditor compares complete serialized cuts with actual child results and checks the frozen test; it does not open SQLite to recompute logical tables. The post-recovery write is closed and reopened within the recovery child, not a third verifier process. Controlled test authority is not production authentication/freshness. Existing malformed sidecars, legacy-path semantics, same-uid pathname replacement, non-Unix qualification and distributed failures are outside this repair's proof. Strict identity and `0600` checks were retained throughout.

## Contents and verification

The archive includes every file and directory of all five completed wrappers, including failure/retry DB/WAL/SHM, actual child commands/PIDs/exit/stdout/stderr, self-reported masks, external full cuts, source inventories and before/after comparisons. It also includes executed and final source snapshots, both drivers, split-patch/static-review capsule, warning bridge, original source copy/admission receipts, byte audits and an independent baseline spotcheck. SQLite was never connected by the evidence collectors; invalid original sidecars were not chmodded or deleted.

`member-inventory.json` authenticates archive member bytes and modes through the outer archive SHA in `manifest.json`. Original inode/device/timestamp evidence is retained in inventories; extraction cannot recreate original inode identity. Access time is excluded because read-only auditing can update it. Use `python verify_bootstrap_evidence.py manifest.json` to verify the archive without extracting or executing anything. The separate audit script records the checks performed against the original run locations; its strict live inode checks are not claimed to survive relocation.

The final four-file source was published as [PR 3833](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3833), head `a47190bb84714cb1262fcd85ebb723081fdb0581`. The saved alignment receipt matches all 9,753 existing file hashes to the final-format inventory, restores only four already-published evidence files, and records no source overwrite or hard reset. [Independent CI run 40152367005](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40152367005), job `121046374239`, is recorded only through its exact-head initial `in_progress`/null-conclusion identity snapshots. This package includes no execution output or success conclusion for that CI.

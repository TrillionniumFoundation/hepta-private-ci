# Windows-current: original 9bd2 attempt, cancelled

This packet preserves one existing run. It did not start, retry or cancel a native test.

| Identity | Value |
| --- | --- |
| Repository | TrillionniumFoundation/hepta-private-ci |
| Source head | `9bd2f589debdba4a93baa363817c3669cb103721` |
| Source tree | `c77785ecb368c44ea699769001a47402c9f50591` |
| Workflow run / attempt | `43021840561` / `1` |
| Original job | `130526720080`, `original-regressions` |
| Original artifact | `13858954851`, 108,223 bytes |
| Original artifact SHA-256 | `93d6c384d7f2d804124825e90b90b81d33a8634456d2b06e5f9b78dc8b535898` |
| Decoded original job log | 152,256 bytes, SHA-256 `9aa9dd6d0adba6b7639e8bc6295f54d2f8608f329acd975fd0a611891d21c8e6` |

The GitHub job concluded `cancelled`; its native step was cancelled and its always-run artifact upload succeeded. The original raw records `KeyboardInterrupt` and `The operation was canceled.` The workflow has a 65-minute job budget, and the observed timing is compatible with that budget. The scheduler's cancellation reason was not independently exposed; this packet does not assert a proven timeout cause.

## Verified scope and result

The unmodified pinned fixture requires 19 groups / 167 distinct cases. The artifact records the first 13 groups, covering exactly their 124 required case IDs with zero retries and the original flags. Independent reconstruction from the raw nextest rows gives **122 strict PASS, 1 LEAK and 1 FAIL**. Eleven groups meet the driver's strict group success rule. A repeated terminal FAIL row is a summary reprint, not another execution.

The two unresolved cases are:

- `unified_exec::tests::elevated_non_tty_cmd_forwards_env_output_and_exit`: `LEAK`. Nextest's summary includes it among seven passed with one leaky; the existing strict driver rejects the LEAK even though that command exited 0.
- `unified_exec::tests::delete_permission_tests::legacy_refuses_before_elevated_four_cell_delete_boundary`: `FAIL`. The ordinary host control preserved Neither and deleted TargetOnly, ParentOnly and Both as expected. The actual elevated child also deleted file and directory in the latter three **outside** cells; the original all-false boundary assertion failed. This is the native elevated path, separate from the earlier Bazel ordinary-parent privilege problem.

Group 14, `core-exit-observation`, has a compilation log ending in KeyboardInterrupt and no nextest run/start/terminal marker. Its nine cases are uncompleted. Groups 15–19 have no started log, leaving another 34 uncompleted cases: **43 total uncompleted**. No selected count or pass is invented for them.

The original helper build succeeded and its receipt binds the setup/runner binaries to the recorded byte sizes and SHA-256 values. `source-before.json` identifies the exact head/tree, empty tracked changes and Cargo.lock SHA-256. There is **no final receipt or source-after record**: final source cleanliness and post-run binary identity remain unobserved.

The separate three hardlink helper tests and the later ordinary-control suspended-child candidate are absent from this original 167-case run. No software result is treated as retained memory benefit, a scored actor result, original-owner recovery or a provider outcome.

## Offline reproduction

Run `python3 verify_original.py` in this directory. It only reads the pinned source, original ZIP and raw log; it verifies member hashes, source identity, exact command/selection, unique nextest UUIDs, terminal statuses, skipped counts, duplicate-row handling and original four-cell outcomes. It produces the same JSON as `ORIGINAL_RESULT_AUDIT.json` and does not invoke Cargo, a host or a model.

`LOCAL_VERIFIER_CORRECTION.json` records an initial offline parser assertion: nextest omits the parenthesized skipped count on the Starting line when zero tests are skipped. The corrected verifier cross-checks the original Summary's explicit count. This was an audit parser correction, not a rerun or change to native results.

The original ZIP is retained intact, including all 20 members. `ZIP_READBACK_AUDIT.json` and the package `FILE_MANIFEST.json` bind every retained byte. The original source pins are in `SOURCE_INDEX.json`; no workflow, scope, source branch or policy was changed by this review.

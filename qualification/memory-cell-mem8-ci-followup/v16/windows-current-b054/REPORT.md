# b054 original Windows-current outcome

The one original invocation, run **43035590081**, job **130573423888**, attempt **1**, ended **cancelled**. The API records job start at 14:08:27 UTC and completion at 15:13:38 UTC on 2026-11-11. The regression step was cancelled at 15:13:28; its evidence upload succeeded. The scheduler's reason is not independently observed. The timing is compatible with the configured 65-minute job budget; this is an inference, not a recorded cancellation cause.

The original workflow and driver declared 19 groups and 167 unique case IDs. Exact original per-group logs and distinct nextest UUIDs show **13 completed groups, 124 distinct selected cases: 122 PASS, 1 LEAK and 1 FAIL**. Eleven groups meet the strict group acceptance rule. The LEAK terminal is kept separate from PASS even though nextest exited zero for that group. Reprinted failure-summary lines are not additional executions.

The fourteenth group, `core-exit-observation` (9 declared cases), was interrupted during compilation and has neither a nextest start nor a case terminal. The final five groups (34 declared cases) have no execution logs. Thus **43 declared cases remain uncompleted**. The artifact contains no final receipt/source-after observation; final source cleanliness and process settlement cannot be inferred from the successful artifact upload.

| Original group | Selected | Reported skipped | Exit | Strict result |
| --- | ---: | ---: | ---: | --- |
| retained-windows-identity | 8 | 207 | 0 | PASS |
| git-process-cleanup | 2 | 33 | 0 | PASS |
| retained-mcp | 3 | 195 | 0 | PASS |
| original-protected-owner | 14 | 366 | 0 | PASS |
| operator-native | 33 | 0 | 0 | PASS |
| shadow-native | 35 | 0 | 0 | PASS |
| sandbox-original-failures | 7 | 180 | 0 | PASS: 6, LEAK: 1 |
| sandbox-native-delete-routes | 2 | 185 | 1 | PASS: 1, FAIL: 1 |
| retained-windows-materialization | 1 | 214 | 0 | PASS |
| canonical-windows-memory-recovery | 2 | 378 | 0 | PASS |
| runner-native-terminal | 4 | 183 | 0 | PASS |
| runner-native-abort | 12 | 175 | 0 | PASS |
| driver-exit-unknown | 1 | 25 | 0 | PASS |

## Actual remaining failures

`unified_exec::tests::elevated_non_tty_cmd_forwards_env_output_and_exit` has an original **LEAK** terminal. The setup handle-allowlist repair authored after b054 is not present in this tested source; no recovery is claimed here.

`unified_exec::tests::delete_permission_tests::legacy_refuses_before_elevated_four_cell_delete_boundary` fails its original outside-boundary assertion. In this invocation, Neither rejects file and directory deletion, while TargetOnly, ParentOnly and Both delete both outside objects. The source still contains the original elevated token policy; no local review or helper repair upgrades this result to isolation success.

The ordinary-host control now exercised the b054 qualification helper. The failing case's original log explicitly retains `verified_before_resume distinct_token=true backup_present=false restore_present=false other_privileges_unchanged=true`, followed by the expected ordinary four-cell outcomes. This marker describes the separate ordinary control child, not the elevated child token. Parent access diagnostics likewise are not elevated-child token evidence. The outer case remains FAIL.

## Identity and limits

Source-before is exactly b0547d2f874c0aeb54dabd3491caa2bee49fcb0b, tree 3f89ddeff13d0af85f4abe2690699107357f1038, with no tracked changes and the original recorded Windows Cargo.lock physical digest. The actual freshly built setup and command-runner artifacts are retained in the original preparation receipt. No final source-after receipt exists.

The complete 108,419-byte original ZIP, SHA-256 fb467cc7e81ed2d8f36177105b42ceff9922bbfce508299d1ef51238a2c1a9d1, has 20 members with successful CRC and byte hashes. The complete decoded job log is 152,322 bytes, SHA-256 bfaddf8ffb3d4d0157af54541fe99f26f665e0f6c6f8025efe919b69e5bf1a5d. `verify_original.py` checks original source pins, 167-case scope, actual selections, unique group UUIDs, all original outcomes, strict receipts, zero retries and incomplete cases against these exact bytes.

The three added hardlink helper tests are not part of this original 167-case selection. Software test names such as original-protected-owner are not evidence of restoring the historical MEM owner or trust domain. No model call, new actor episode, CI replay, host task or source-ref mutation was performed by this audit. Earlier 9bd2 outcomes are not used as b054 test results.

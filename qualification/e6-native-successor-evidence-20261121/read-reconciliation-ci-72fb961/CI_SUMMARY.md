# Exact-head daemon CI: tests passed; maintenance and retention failed

The original naturally triggered daemon workflow on PR #6858 completed with **failure**, on its only attempt. Its native test phases passed: ordinary **2,184/2,184**, including the original lost-RPC regression case, followed by **46/46** actual Root parents. The failure occurred after those tests, during formatting and maintenance-evidence retention.

## Identity and original evidence

- PR: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6858
- Run: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44867872646
- Job: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44867872646/job/136735522608
- Attempt: **1**; no dispatch or rerun was performed by this audit.
- Executed source: `72fb96148a3d12db0d3482f46ab0653f7353d532`.
- Executed tree: `8e90cff71a6bc5ccdbe85c1d9f50c03fe546a8f0`.
- Immediate parent: `84721f3da92ffaac3e7c7e2e39de2df985834370`.

The exact original artifact ZIP, ID **14693493582**, is retained as `daemon-learning-native-72fb961-attempt1.zip`: **5,585,270 bytes**, SHA256 `dbead6f4108832f2403dc9f939c6395082257c79b56cf5474812e01550b18f73`. Its downloaded bytes match GitHub's artifact size and digest. All **42** regular file members were safely restored into `artifact-originals/`; their byte inventories are in `ARTIFACT_MEMBERS.json`. No archived program was executed.

The complete GitHub job-log tool's returned UTF-8 content, including its initial BOM, is retained as `FULL_JOB.log`: **4,770,606 bytes**, SHA256 `20cb18d711f3b19d60281a172463ce5b8537391b9041c0ce37a57a727c8b6eab`. `FULL_JOB.log.gz` is a new deterministic compression of those same decoded log bytes; `LOG_RECEIPT.json` binds both forms. The original HTTP transfer encoding is not claimed to be preserved.

## Canonical native results

| Phase | Canonical cases | Passed | Failures / errors / XML skips | Original executor elapsed | Nextest test elapsed |
|---|---:|---:|---|---:|---:|
| Ordinary six-package suite | 2,184 | 2,184 | 0 / 0 / 0 | 663.0510680539999 s | 268.533 s |
| Selected Root parents | 46 | 46 | 0 / 0 / 0 | 28.760399202999906 s | 26.199 s |

Executor elapsed includes work outside test execution, including compilation. These are nested measurements and must not be added. The original job's API start/completion interval is **2,146 seconds** (04:48:30 to 05:24:16 UTC). It also includes checkout, dependency preparation, helper compilation and maintenance.

Nextest separately reported **159 skipped** for the ordinary invocation and **1,614 skipped** for the Root invocation. These unselected/skipped entries do not appear as skipped cases in the two canonical XML files. Their counts must not be merged with canonical executed cases.

Canonical evidence:

- `artifact-originals/ordinary.xml`: 518,564 bytes, SHA256 `212cbedd358e54625ca393706f65bce61e84910223c6fc555a1d60b973052336`.
- `artifact-originals/root.xml`: 12,629 bytes, SHA256 `6325ae7581923b384ea88f268cb4baee23ad70dc83eb021d0a9e64809bf42178`.
- `ordinary.json` / `root.json`, their collection summaries, and both launch records bind the commands, source identity, clean before/after states, return code 0, no timeout and no output-limit failure.
- `root-prior-junit-excluded.xml` is byte-identical to the ordinary JUnit and is not counted again.

The unique ordinary case `cell_generation_control::tests::lost_rpc_reply_and_queue_capacity_cannot_duplicate_original_dispatch` passed in **0.078 seconds**. The test source on this commit retains the original 30 ms RPC timeout and five-second terminal wait, reads the same request on uncertainty, and checks one worker call, exact replay/reopen, conflict rejection and durable-byte preservation. This is one passing regression-test observation; it does not establish the historical failure's physical cause or general production exactly-once behavior.

## Root execution and source boundary

The workflow naturally entered Root after ordinary success. The original launch requires euid 0, and actual logs show `Root test uid=0`. Setup succeeded at `/run/hepta-daemon-learning-44867872646-1`, using separate `source`/`bind` and `witness-source`/`witness-bind` bind mounts plus checkpoints. Both recorded unmount commands later returned 0.

The original fixed list contained **46** Root parents. Independent XML comparison confirmed exactly those 46 unique names, with no missing or extra parent. The ordinary and Root canonical case identities have zero overlap. The complete fixed list and fixture declaration are retained in `EXPECTED_SCOPE.json`; that file is explicitly a static-scope observation, while `TERMINAL_VERIFICATION.json` records the actual execution checks.

Checkout, before-tests and after-tests inventories each contained **16,559 files**, with identical inventory SHA256 `a6181acc30f9c394727bfabc92edac1a380df4a73c5ae7ae32f310abc1cb214c`, clean worktrees and the exact head/tree above. The reported passing native results therefore belong to the clean published head, before maintenance mutations.

These 46 Root parents are the original engineering fixture list. They do not replace the separate lifecycle-v1 warm Adopt failure or the two cold parents that had zero attempts. No external student-weight adoption, fresh-D recovery, scientific gain, FinalUse or settlement claim follows from these CI counts.

## Actual maintenance failure

The scoped six-package `just fix --locked --offline …` returned 0. The subsequent original command was:

```text
just fmt --base b8e8c6e82abc1479c573f61a5e17d28d581e6cad
```

It returned **1**, without a timeout or output-limit failure. The original `fmt.log` shows `rustfmt --edition 2021` applied to this historical evidence snapshot:

```text
evidence/e1e6-execution-readout-20261120/references/e6-1a979-lane-review/source/codex-rs/hepta-agentd/src/cell_q24_learning_owner_error.rs
```

The errors identify let chains at lines 45, 52 and 53, requiring Rust 2024. This is the daemon formatter failure, and is distinct from the separate blocking workflow's two whitespace-format diffs.

The final maintenance patch contains four changed paths:

1. `codex-rs/hepta-agentd/src/ordinary_q24_source_keeper_tests.rs`
2. `codex-rs/hepta-agentd/src/production_initial_q24_writer.rs`
3. `evidence/e1e6-execution-readout-20261120/references/circuit-source--cross_neural_circuit.rs`
4. `evidence/e1e6-execution-readout-20261120/references/e6-1a979-lane-review/source/codex-rs/hepta-agentd/src/cell_q24_learning_operation_lane.rs`

The retention guard then refused path 3 because maintenance is allowed to change only `.rs` files under six declared crate owners. The guard retained `maintenance.patch`, but failed before publishing a maintenance summary or qualification-status file. `retention-error.json` records this separately. The later binary compile-only check was not reached. The overall workflow remains failed; neither passing native tests nor source cleanliness before maintenance closes this maintenance failure.

`FORMAT_SCOPE_REVIEW.md` explains the selector/owner mismatch and a minimal separately reviewable fix proposal. No formatting, workflow change or test rerun was performed for that review.

## Other candidate gates

The same candidate's `blocking-ci` run **44867872686** failed. Its API results and the complete Rust-format and closed-set job logs are retained under `other_gates/`; `OTHER_GATES_SUMMARY.json` records the scope.

Both inspected blocking jobs actually checked out merge commit `3f1a55d5ae6ddd21ab819f065f945630698b132c`. The Git API confirms its tree is the same `8e90cff…` as the candidate head, while the commit identities remain distinct.

The Rust-format job reported only the two source paths numbered 1 and 2 above, not the newly changed `cell_generation_control_tests.rs`. The closed-set main checker emitted `PASS_HEPTA_CALLER_CLOSED_SET` after scanning 6,911 Rust files, but the subsequent source-closure QA reported `Ran 1014 tests in 244.423s; FAILED (failures=2, errors=4)`. These counters include subtest error events; no passed-case count was inferred by subtraction. Actual diagnostics are retained, without assuming a baseline cause or applying repairs.

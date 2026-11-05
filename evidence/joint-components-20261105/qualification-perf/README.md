# Qualification append cost: bounded conservative change

Status: **Two targeted native tests pass; complete package qualification and executed-binary attribution remain pending.** This change is separate from the three-file effect-recovery patch.

## What changed

On the fixed Hepta base `1556a4df6e279055fd8196f81a4ca2fe0f19384a`, every qualification append loaded and decoded the candidate's prior ordinary receipts, copied their references, sorted them, serialized the aggregate and computed its SHA. The independent-decision validator immediately returned success for ordinary claims and decision revocations, so those classes did not consume the aggregate digest.

The two-file patch retains the same query, ordering, `LIMIT 8193`, rejection above 8192 rows, per-row decoder, transaction snapshot, and validation order before lineage/replay changes. For the existing early-return receipt classes it omits only the unused reference vector, sorting, aggregate serialization and digest. Real independent decisions still compute and validate the original digest. Historical canonical/projection corruption is still rejected.

The new negative control changes a stored payload projection while retaining the canonical envelope, verifies that an ordinary append fails closed, repairs the exact projection/immutability trigger, then succeeds with the **same signed message and sequence**. The failure must not consume replay state. The original 512-reference test and its limits are unchanged.

## Native source and actual results

The isolated native candidate is `4dce06a9945fc54482f546c9dfb7cbb7a4716ccc`, tree `ace984bea899295f7e8fa6666fc78cfd49ad2a92`, parent recovery component `a877333eff1577179fce8b1ceb6edf4322440e03`. It was fully materialized with 11,825 tracked files, no hidden index flags and a clean byte/mode identity. Existing recovery source and common/parent configurations stayed unchanged. Original `just fmt` preparation occurred before the clean candidate commit.

| Native check | Actual result |
| --- | --- |
| Exact 1556 baseline, original `claim_query_rejects_more_than_512_references` | TIMEOUT at 60.006 seconds, under the original local profile. Preserved under `../native/baseline-control/`. |
| Recovery a877 full library, same original test | TIMEOUT at 60.006 seconds; 159 other tests passed and one was skipped. |
| 4dce, same original 512-reference test | PASS, 54.595 seconds. |
| 4dce, historical projection corruption / same signed attempt after repair | PASS, 0.488 seconds. |
| Targeted original wrapper | PASS, two passed and zero failed; 147.033453 seconds including compilation. Source before and after were identical and clean. |
| Additional ELF collection requirement | Incomplete. The observer captured no test ELF, so its enclosing pipeline exited 1 after the original test wrapper passed. No binary hash is backfilled. |
| Full library, scoped original Clippy/fix, final format gate on 4dce | Not yet executed. |

Both tests used Rust 1.96.0, pinned nextest 0.9.103, the original dependency lock, two build jobs, original features and test profile, the original 600-second wrapper and unchanged local per-test 60-second timeout. The finite selector skipped 160 non-selected tests and ran the two named controls in one test binary. This is not a full-suite pass.

The exact command is recorded in `native/attempt-1/two-controls.json`. Its SHA256 is `b419bc79650eb30997e04b8273399fbda65a94bdf2d7d163ff6ea34dd6a1fda8`; the complete raw log SHA256 is `a0a20dd922f79425c6abeac43341521a4ca5bf991484f36b59342a4981aee9d9`. The outer collector failure and empty capture list are retained in `two-controls-status.json`; they are not substituted for the Rust test result.

The observer only inspected each process leader's task-children file, which is insufficient for a multithreaded runner, and did not bind start times or recheck PID/argv/executable identity. The final combined candidate must use the team's separately reviewed `native/test_elf_capture.py` collector. This attempt establishes exact source plus raw test-log evidence, not complete executed-binary attribution.

## Deliverable and remaining limits

`qualification-unused-set-digest.patch` is the actual native-formatted Git diff of the two performance files, SHA256 `903269d4d4741e051437dcc6eaeaf5e6a455a4a88fab10f4b0606e415ca8e0b7`. Exact files are under `hepta/codex-rs/hepta-evidence/src/`. The reviewed pre-format input is retained separately for provenance. The native preparation logs, environment, receipts and complete raw output are under `native/attempt-1/` with their original hashes.

Historical decoding remains cumulative **O(n²)** across repeated appends. The baseline results are timeout-censored, so these records do not establish an exact percentage speedup or a robust long-term growth budget. A single 54.595-second result does not close sustained-storage/cost requirements. Complete package/lint/format gates and the final H1 source/binary qualification remain required.

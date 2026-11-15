# MEM12 native execution: recovered final evidence

**Frozen-source software qualification passed. Memory-benefit adoption remains HOLD.** The original evidence and two continuations establish **42 passed Rust test executions, 0 failed, 0 skipped**, plus **8 passed strict-isolation cases**. Verified V8, the Codex build, scoped fix, and final format also passed. These native attempts made **0 real model calls** and scored **0 memory-benefit episodes**.

Qualification applies only to source commit `811e0e27190066e81a23eebed8ad559ae67d228e`, tree `2043cbf11fd00662cc23562123c27ae4e6f72580`. The source stayed clean; all 25 archived postimages match the original attempt, and the source-rewrite patch is empty. This does not qualify the full evidence-branch tree or MEM13, MEM14, or MEM15.

## Established execution results

| Stage | Passed | Failed / skipped | Original execution retained |
| --- | ---: | --- | --- |
| Strict isolation | 8 | 0 failed | Original attempt: 6 admission and 2 Linux namespace cases |
| Memory episodic | 11 | 0 / 0 | Continuation 01; original JUnit recovered without rerun |
| Agentd episodic | 7 | 0 / 0 | Continuation 02 |
| Agentd qualification profile | 1 | 0 / 0 | Continuation 02, `qualification-cognitive-write` feature |
| Native delivery | 7 | 0 / 0 | Continuation 02 |
| Protocol | 16 | 0 / 0 | Continuation 02 |
| **Rust total** | **42** | **0 / 0** | **11 prior executions + 31 new executions** |

These are execution counts across five Rust reports. One profile case also appears in the ordinary agentd report under a different feature configuration; 42 is not a count of distinct test names. Continuation 02 verified the original memory evidence and strict-isolation receipt and did not repeat those completed stages.

All four new JUnit run UUIDs occur in their respective original logs, differ from the previous report at the collector path, and have every case timestamp inside the corresponding execution receipt. Their counts, names, digests, and bindings appear in [CONTINUATION_02_VERIFICATION.json](CONTINUATION_02_VERIFICATION.json). The native delivery report includes the real-agentd-worker fresh-context/final-use-tombstone test; the agentd report includes `native_predecessor_forget_closes_episodic_context`. These are the tests in the frozen source, with no claim about subsequent implementations.

## Final terminal and source identity

Continuation 02 job `1a1cedb0568-2564-18ae` terminated **succeeded, exit 0, `timed_out=false`**, with `output_complete`, `output_durable`, and `terminal_publication_confirmed` all true. Its original RESULT is 42,212 bytes, SHA256 `6350c2cf293438473e606f1b616650713176bc2ef87510901f23a8061817496d`; the terminal SDK payload is 908 bytes, SHA256 `4d7af7be5519a5904deadebc082d8ef3bfec182e65d665145d38f4dc76636c43`.

The original RESULT records identical before/after Codex binary digests: 560,467,144 bytes, SHA256 `d1d7220a54e11f3bd8d96dd997e45db7184939961c8aa433c9eb8d95ee2e91fe`. The binary itself is not bundled; this statement is based on the retained runner measurements. The source postimages and receipt/log/JUnit bytes are bundled and were independently hash-checked during recovery.

## Earlier failures remain part of the record

The original job `1a1cea67111-2564-1763` failed with outer exit 1. Strict isolation had passed, but `cargo test --no-run` failed with phase exit 101 because `aws-lc-sys` bindgen using Clang 21 could not find `stddef.h`. **Zero Rust tests executed in that first attempt.** Its original failed RESULT, logs, terminal SDK payload, and complete archive remain unchanged.

The environment repair unpacked `libclang-common-21-dev` version `1:21.1.8-6ubuntu1` into the task-private sysroot and set `BINDGEN_EXTRA_CLANG_ARGS` to its resource directory. The package SHA256 is `c7188f593d77017a4ebb6fea76bb4b5180a3e5a1e7b9f0e3dbd5f5abf7e7183e`. This changed neither source nor system packages.

Continuation 01 job `1a1ceb9bc10-2564-1808` then ran the 11 memory tests successfully, with command exit 0. Its wrapper nevertheless reported failure and outer exit 1 because our continuation collector looked for JUnit in the wrong directory. We recovered the original correct-path JUnit, receipt, and log without replay. The JUnit is 2,717 bytes, SHA256 `6c3e2fbc6551df44daa77d4b74349eee80afcf0d3237318759f7f2d03ea02af2`; UUID `372c4563-0ab7-41df-ac66-f2a8d9c87bb8` binds all 11 case timestamps to the original receipt and log. The original failed RESULT has not been rewritten as passed. Both earlier outer failures had `timed_out=false` and complete, durable, confirmed terminal output.

**Correction: the original collector path was correct.** The earlier hypothesis that the original collector was defective is withdrawn. In Nextest 0.9.151, the default store is workspace-relative `target/nextest/<profile>`, independently of `CARGO_TARGET_DIR`: see the fixed [default configuration](https://github.com/nextest-rs/nextest/blob/cargo-nextest-0.9.151/nextest-runner/default-config.toml#L4-L7), [store-directory resolution](https://github.com/nextest-rs/nextest/blob/cargo-nextest-0.9.151/nextest-runner/src/config/core/imp.rs#L824-L825), and [JUnit resolution](https://github.com/nextest-rs/nextest/blob/cargo-nextest-0.9.151/nextest-runner/src/config/core/imp.rs#L1232-L1241). Continuation 01 introduced the incorrect target-dir-based path; continuation 02 used the corrected workspace path. The original missing-header build failure is separately established.

Continuation 02's initial submission acknowledgement was UNKNOWN. Exact same-key reconciliation returned the original running job (`reused=true`, `retried_launch=false`); the later terminal above establishes its final outcome. The original UNKNOWN submission and running reconciliation remain preserved, with final observations appended separately.

## Complete originals and recovery indexes

| File | Scope |
| --- | --- |
| [native-811e0e27.tar.xz](native-811e0e27.tar.xz) | Complete original attempt archive: 149,224 bytes; 101 members, 75 regular files; all 74 original manifest entries verified. |
| [native-continuation-811e0e27-02.tar.xz](native-continuation-811e0e27-02.tar.xz) | Complete final continuation archive: 166,532 bytes; 82 members, 66 regular files; all 65 original manifest entries verified. Includes the recovered original memory evidence. |
| [checkpoint.tar.xz](checkpoint.tar.xz) / [CHECKPOINT_MANIFEST.json](CHECKPOINT_MANIFEST.json) | Original recovery context, initial submission/reconciliation, raw SDK material, original terminal, and header repair; unchanged. |
| [archive-recovery.tar.xz](archive-recovery.tar.xz) / [ARCHIVE_RECOVERY_MANIFEST.json](ARCHIVE_RECOVERY_MANIFEST.json) | Complete original archive transport: SDK pages, reconstructed payloads, version-bound chunks, and requests; unchanged. |
| [continuation-recovery.tar.xz](continuation-recovery.tar.xz) / [CONTINUATION_MANIFEST.json](CONTINUATION_MANIFEST.json) | Continuation 01 result/terminal/JUnit/receipt/log and correction, plus continuation 02's original submission/reconciliation; unchanged. |
| [continuation-02-recovery.tar.xz](continuation-02-recovery.tar.xz) / [CONTINUATION_02_MANIFEST.json](CONTINUATION_02_MANIFEST.json) | Final continuation source readbacks and progress, seven complete original SDK payloads, and the complete archive transport: 3 chunks / 15 SDK pages / 3 payloads. |
| [EVIDENCE.json](EVIDENCE.json), [ARCHIVE_VERIFICATION.json](ARCHIVE_VERIFICATION.json), [CONTINUATION_02_VERIFICATION.json](CONTINUATION_02_VERIFICATION.json), [SHA256SUMS](SHA256SUMS) | Machine-readable results, original/final archive safety and content verification, and whole-file checksums. |

The continuation 01 standalone archive was observed remotely as 147,044 bytes with SHA256 `8f08e07e530eff7e5d3ce1ae70848559044d9790f2f0262e74da61447e120380`; that archive was not downloaded for this publication. Its required result, terminal, memory JUnit, receipt, log, and raw SDK readbacks are complete and retained separately. This limitation does not apply to the complete original or continuation 02 archives.

Final continuation archive SHA256: `2a46e59a61c6b4afc94cb2bca2d5fa5847484705d9b6ade4672fd4365a2e702c`. Original archive SHA256: `5c04dd9bef70c43b6a338f44a254e4b28f4e0533c756a4cba733aeb47882ed7a`. Recovery rejected unsafe tar paths, links, special files, and duplicate members, and verified the original manifests, source postimages, stage receipts, logs, JUnit UUIDs, and case time windows.

This publication task only recovered and verified evidence; it launched no native jobs, tests, or model calls. The earlier negative model evidence in the parent history remains intact. Passing these software controls provides no scored memory-benefit result, so adoption remains **HOLD**.

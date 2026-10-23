# Original Objective sender: final owning-package execution evidence

This bundle preserves the completed **319-test checked-observation** and **322-test acknowledged-snapshot** gates. It binds each result to its own source stage, retains complete raw stdout/stderr and JUnit, and adds the final format and Clippy receipts. It introduces no implementation or authority provider and runs no new build.

## Source stages and actual results

| Stage | Immutable source commit | Original memory package result | Evidence |
| --- | --- | --- | --- |
| Frozen original owner | `4869044893f114bcb1d7235830c7313638df8254` | 317 passed; 8 skipped | [Already-published original final receipt](../2026-10-23-objective-sender/memory-all-final.json) |
| Checked observation | `7f86518d7f179c068d60c6cf26d41710d3540579` | 319 passed; 8 skipped | [Receipt](checked/checked-memory-all-01.json), [complete stderr](checked/checked-memory-all-01.stderr), [JUnit](checked/checked-memory-all-01.junit.xml) |
| Acknowledged snapshot | `db91f9ec316ba1472e7adf97f8415949de012469` | 322 passed; 8 skipped | [Receipt](acknowledged/acknowledged-memory-all-01.json), [complete stderr](acknowledged/acknowledged-memory-all-01.stderr), [JUnit](acknowledged/acknowledged-memory-all-01.junit.xml) |

These counts are separate complete runs on successive versions. They are not additive and the 317 result does not qualify either later delta. Nextest reports eight skipped/ignored tests outside the executed testcase list. The original JUnit files contain 319 or 322 testcase records and `skipped=0`; their raw representation is retained without rewriting. [execution-index.json](execution-index.json) lists every executed testcase, both new checked tests and all three new acknowledged-snapshot tests.

Both runs used the original command:

```text
just test --locked --cargo-profile dev-small --build-jobs 1 --test-threads 1 -p codex-hepta-memory --lib
```

The original `just fmt --check` succeeds for the checked stage, the acknowledged stage, and the final post-Clippy source state. Both original `just fix -p codex-hepta-memory --locked --profile dev-small --lib` commands exit zero. **Final Clippy still reports 28 memory lib-test warnings and 2 memory lib warnings (duplicates), plus an upstream PTY deprecation warning.** The checked stage reports 27 lib-test warnings. These are not zero-warning or `-D warnings` claims; complete diagnostics are preserved in [the final stderr](acknowledged/acknowledged-clippy-fix-01.stderr). The final format receipt is [acknowledged-format-final.json](acknowledged/acknowledged-format-final.json).

## What the two deltas change

`retain_observation_checked` runs the host's bounded synchronous semantic predicate against the retained snapshot inside the same original `BEGIN IMMEDIATE` transaction that appends the observation. A rejected predicate produces no append or checkpoint. An exact retry rechecks and re-ACKs without another event. The deterministic negative control demonstrates that separate prechecks can admit conflicting generic appends; the positive concurrent test admits one publication and preserves idempotent acknowledgement.

`snapshot_acknowledged` reads the original retained snapshot and obtains the independent current-cut ACK while holding that same original SQLite writer transaction. The snapshot becomes returnable only after the ACK and live authority checks. Checkpoint refusal or cancellation does not promote a committed local observation into an acknowledged projection. It does not append an event or grant a new send/cancel right. Its three original-owner regressions cover failed-ACK recovery, recovered local cancellation, and retention of the original write lock throughout the ACK.

These changes retain the frozen owner's separate typed Objective admission domain in the original CognitiveStore/ProductionDurableWriter. They do not reuse the FinalUse effect lifecycle or add a database, writer, runtime, UI ledger or default checkpoint. Checkpoint deadlines remain **cooperative** Tokio deadlines: callback polls and synchronous verifier/clock/checked predicates must be bounded, nonblocking and non-reentrant where required.

## Exact workspace and source identity

The execution baseline is original Hepta head `16418ddc3416a38a122b883cee46e2d3583cbd41`, tree `43fde98e9ea789b81b941e48bb65300c76c4292c`. All seven final execution receipts record verification of all **9,111 original blobs plus exactly 19 candidate paths**, before and after their command, with no unrecorded difference. The original workspace was not narrowed or its manifests replaced. It has **193 effective Cargo workspace members** according to its preserved original `cargo metadata` receipt; the root manifest contains 187 explicit member entries. This is a complete-workspace input claim, not a claim that all 193 packages were tested.

The original `Cargo.lock` SHA-256 remains `83651f11dea7f58dc96f3d119c120ab2bd8019e418979ab091ef49de7cceb9e8` before and after every command. [original-workspace-integrity.json](original-workspace-integrity.json) binds the original manifest/lock blobs and all 193 member manifests. Tool versions and environment are in each original receipt: Rust/Cargo 1.95.0, nextest 0.9.149, just 1.40.0. There is no miniature replacement manifest or reconstructed reduced test harness.

[source-version-binding.json](source-version-binding.json) records all 19 source rows at each stage. The final executable Rust files match the `db91f9ec…` candidate. Its `OBJECTIVE_SENDER.md` update is a separately hashed docs-only delta: the test overlay retained the earlier document bytes. Therefore this bundle does **not** assert that every byte of the entire published Git tree, including documentation and evidence, was present in the on-disk test overlay. The two final Rust hashes are `abdfbd3d027ff66807c767169efc25911d486dc34cab19d0fedb3eb62245d90a` and `41c9087f316aa331638591cba0fd7abce3b618e2044374b19ac286af2e9b6462`.

Original authoring manifests and preimages are copied verbatim. Their then-current “unexecuted” strings and local prepublication tree remain historical records; subsequent receipt timestamps and matching file hashes provide the execution result. The checked manifest also contains a historical Desktop adapter row, which is outside these Hepta owning-package tests. The old `source-manifest-before-deadline-doc.json` is retained as history, not as the final source identity. Both quality-preimage indexes allow exact reconstruction of all 19 pre-Clippy files from immutable source commits without duplicating those already published source blobs.

## Evidence retention and replay

The `checked/` and `acknowledged/` directories contain complete original receipts, raw stdout/stderr (including genuinely empty files), JUnit, execution runners, overlay identities, patches and source/preimage/documentation manifests. No final log is truncated or replaced with an earlier failure. The runners are archived as the actual original execution helpers; their original workspace-relative imports and absolute task paths are retained and must be reconstructed before reuse. [The frozen verifier](../2026-10-23-objective-sender/owner_overlay.py) and its original 46 evidence files remain in the earlier prefix and are not uploaded again.

[bundle-files.json](bundle-files.json) inventories the exact bytes, SHA-256 and Git blob for every other file in this bundle. The publication entries separately include that inventory itself. The source commit/tree IDs are supplied by the publisher and locally bound to exact file hashes; this packaging step does not perform new remote lookups or mutation.

[final-binary-and-cache-transition.json](acknowledged/final-binary-and-cache-transition.json) records the 46,495,368-byte final test binary at SHA-256 `22117d7d01e2d6eb035e024e345bc364079a99bddb4c435f20aed58e21372f83`. It also records deletion of only the reproducible task-owned build cache after all gates, with no active build process. The binary is an identified executed artifact, not an archived executable in this bundle; original source, lock, dependency cache and evidence were retained.

## Remaining production and execution boundaries

The three Agentd bridge tests are authored but unexecuted. Memory package success does not qualify the Agentd package, its full production factory, the Desktop adapter, native guest/ELF/QEMU lifecycle, hardware, or live model dispatch.

An independently authenticated, fenced, durable **production current-cut checkpoint provider is still required and not implemented by this slice**. Test checkpoint providers establish contract behavior, not that missing production authority. A recovered plain snapshot cannot substitute for an independently acknowledged snapshot. The current-cut witness also remains distinct from the original Objective journal publication anchor; a local cancellation is not original RunCancel.

The legacy fresh-store initializer is used only as explicit test genesis. Production recovery still enforces the original protected generation/current-cut/schema and sidecar permissions; the tests do not establish an authorized upgrade path for an old-schema production store. Such an upgrade requires its own original-host authorization and independently acknowledged new cut. None of these missing capabilities is waived by the passing memory tests.

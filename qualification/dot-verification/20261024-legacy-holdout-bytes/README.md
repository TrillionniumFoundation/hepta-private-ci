# Actual V1 writer to V2 reader file-byte regression

Old writer production source: b98961ceb71414490e1c6ae397cf635bca3093f4.
New reader production source: b2964156764e174b396407c0c981d6fad043b204.
Two separate worktrees were used. No production source, Cargo dependency/lock,
workflow, owner authorization or public API was changed. The new source patch is
only one test module plus its declaration in paired_owner_tests.rs.

## Why this test is different

Existing tests built old-shaped plans/snapshots using the new compiled library.
This fixture was written by an executable linked against the actual old source.
The old generator uses the real LockedFileFinalHoldoutCasStoreV1 and
FencedFinalHoldoutOwnerV1, writes fence/event-1 OPE consumption, closes the owner,
and retains its raw bytes, independent anchor and full original receipt.
The reader embeds precisely these 483 bytes as a Rust constant; it does not
reconstruct a journal using the new writer. Original hex and witness are retained.

Old journal SHA256: 386c931f72282c0726dd687c807c07a5474acf0a1c1332828cae3cb77e85bfe7.
Original state digest: 7ffcc615e54d8b4c0cc1f776097c246973055266d8af8dfe6d65f3ac85a55d62.
Original record/head digest: 5cbe204dd1a8e8ed1ef9221ce0d672d5db2946c3fcbc416783079bba98ae0cc5.

## Actual results

- Old real generator: 1/1 passed, 0 skipped, 483 bytes produced.
- Focused new reader: 3/3 passed; 127 unrelated library tests filtered out.
- Full new eval library: 130/130 passed, 0 skipped, 0.410 seconds test time.
- just fmt: exit 0. Scoped --no-deps strict Clippy for lib/tests: exit 0.
- git diff --check: exit 0.

The new reader checks the old anchor and record/head digest; legacy retry is
explicitly IdempotentReplay and leaves every file byte unchanged. Appending a
paired record preserves the complete original prefix, adds event tag 2 and
increases record_count to two. After close/reopen, paired replay is explicitly
IdempotentReplay; old replay preserves the original record digest, and the
anchor plus entire mixed file remain unchanged. Restoring the old backup below
the retained new anchor returns Rollback without rewriting bytes. Corrupted
checksum and truncated legacy files return Corrupt without rewriting bytes.

An initial offline attempt failed before compilation because registry metadata
for arbitrary was absent. The normal official Cargo registry resolved dependencies
without changing Cargo.lock; that failure and subsequent successful log remain.
Repository-pinned Rust 1.95.0, jobs=1, no incremental/debug info and a separate
build target directory were used. There were no model/provider/socket calls.
Pre-format source and executable hashes are retained; tests were not rerun after
formatting, as AGENTS requires. Independent review can compare exact pre/post
format bytes. No dependency-wide Clippy, Bazel or workspace-wide pass is claimed.

## Reproduction

For fixture regeneration, checkout exact b98961 into an isolated worktree and
copy legacy_golden_writer.rs to codex-rs/hepta-intelligence-eval/tests/. Set
HEPTA_GOLDEN_DIRECTORY to a nonexistent directory, then run from codex-rs:
just test --locked -p codex-hepta-intelligence-eval --test legacy_golden_writer.
This uses the real old writer, not a current-code fixture generator.

For the new reader, apply the two test files to exact b2964156 and run:
just test --offline --locked -p codex-hepta-intelligence-eval --lib.
Official dependencies must be available first. Source identities, environment,
commands and output hashes are also recorded in invocations.json and SHA256SUMS.

## Limits

This is one small actual persisted-format migration, not exhaustive backward
compatibility or power-loss qualification. The old reader need not understand
new event tag 2; downgrade compatibility is not promised. FinalHoldoutCasRecordV1
still changed its public journal field from a V1 snapshot to a V2 envelope.
Passing file-byte migration does NOT make old Rust callers source-compatible.
No NDU census was rerun, no failed calibration threshold relaxed, and no new
scientific benefit, owner authority or production qualification is asserted.

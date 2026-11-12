# Packaging and provenance

This is an independent follow-up package. The 93 files published in evidence commit b29869e856d08db1bfb066116a9c443376ccc57d remain unchanged. The frozen PUBLICATION is not edited and all ordinary qualification counts remain zero.

## Original bytes and derived records

Files copied into this package retain their complete original local bytes. PACKAGE_MAP.json records original locations, physical hashes and relocations. Original ARTIFACTS.json, originals-manifest.json, VERIFIED_MANIFEST.json and other indexes are preserved without rewriting their paths. Those indexes describe their original directory layouts; use PACKAGE_MAP.json to resolve relocated or deduplicated files here.

The repair's four copies under evidence/original-full-source-8faf are deduplicated into source-8faf-failed by exact bytes. Six standalone repair source postimages and standalone maintenance Rust source files are omitted. Their paths and exact hashes remain in the original indexes and PACKAGE_MAP.json; the repair patch and published exact-source comparison are retained. No omitted standalone .rs file is represented as physically included. Original request/SDK payloads and patches may contain source text as part of the original execution record.

The old source log has an explicitly recorded original-log-prefix-recovery.json. The caller terminal directory contains both the local payload copy with a trailing newline and operation-original-sdk-payload.exact.json: the latter is the 5,949-byte original SDK payload matching SHA-256 509bd1262fa1f4b1868d28be012fc352948afc36b49b8eadc2ac977ebc6a745c. Preserve their distinct physical hashes; do not treat the normalized copy as the original native payload. Format-result.from-pty records are derived extractions; corresponding original terminal receipts and raw stdout remain included.

## Execution identity

Every interpreted machine result in PROGRESS.json identifies its actual source commit/tree or an explicitly described local-postimage variant. The 66-test local repair pass is not relabeled as execution on published cc22. The original 8faf source failure and its independent fullcaller failure remain failures. The unexpected Training readback service caller is a separate finding from the C Trainer receiver repaired for the source suites.

The 8faf maintenance driver reported status=passed because just fix exited 0, while it left one changed source file. This package labels that command success with a source change, not a clean-source gate pass. Its isolated rustfmt subsequently changed the retained helper postimage. The later cc22 just fmt and just fix runs both have clean, unchanged inventories and zero postimages.

Source, maintenance and caller inventory SHA values use different original row formats and materialization scopes. Equality is checked only within each run's own before/after pair. A tracked-path count does not claim every path was physically materialized in every worktree.

## Large originals not included

The full compressed source/maintenance/caller inventory .gz files remain in their original desktop evidence directories; they are not bundled here. The small before/after metadata preserves each actual logical inventory digest. REMOTE_INVENTORIES.json distinguishes the source-before compressed file whose size/SHA/version was independently read from files for which only the original run's logical digest and original path are retained. No missing compressed file is silently reconstructed.

Native helper binaries, large compiler JSONL output and cache data are also not bundled; original helper artifact/transfer manifests retain available size/SHA/location records. A helper build or verify-only exit 0 is not a native test pass. Focused native, Root native and post-repair fullcaller results remain pending until their separate terminal originals are added.

The source gate's 600-second budget, scope and original hepta_ci_exec command are unchanged. Only canonical source identifiers, isolated paths and attempt keys changed. Transient read errors are transport evidence, not process exit statuses. The original source job was neither restarted nor cancelled.

## cc22 original log recovery

The full 90,825-byte driver log was assembled from independently read immutable segments and matches its original recorded SHA-256. Its first 89,504 bytes exactly match the original hepta log SHA-256 recorded by hepta_ci_exec. That complete original log is preserved through explicit prefix derivation, not claimed as a separate full disk read. An independently read 65,536-byte middle segment also matches it byte-for-byte. The derivation is recorded in source-cc22-passed/source-result/original-log-prefix-recovery.json. No further read or test dispatch was used to fill the final segment.

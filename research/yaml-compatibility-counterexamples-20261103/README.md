# YAML compatibility counterexamples — research only

**HOLD: this is rejected migration research, not production code and not an advisory closure.** No production paths, dependency manifests, lockfiles, or workflow gates are changed.

## Recovery status

The execution environment reset after the bounded experiments completed. The original scratch and tmpfs trees disappeared before the final handoff archive was saved. This directory distinguishes three kinds of evidence:

1. **Exact preserved tool output:** `preserved-tool-data/independent-1_3-tool-result.json` and its stdout contain the original independent serde-saphyr 1.3 probe output returned by the tool (24 observations plus an execution footer), recovered from surviving tool state. No missing records were synthesized.
2. **Hash-verified patch recovery:** the official serde-saphyr 2.1.0 tarball was downloaded again and checked against the original SHA256. All three modified upstream file hashes match the values printed by the actual pre-reset patch run. `PATCH_RECOVERY.json` records that verification; `local-application-tags.patch` is 5,633 bytes. The recovery script is new and did not compile or run a parser.
3. **Observed aggregates and reconstructed sources:** `OBSERVED_SUMMARY.json` faithfully records aggregate results already returned by completed tool calls. The complete later per-case logs and command receipt files were lost. Reconstructed probe sources are labelled **RECONSTRUCTED_NOT_RERUN**. They must not be presented as byte-verified original binaries or a new successful test run.

The original compiler was Rust 1.95.0, using official serde-saphyr 2.1.0 and granit-parser 2.1.0 with deserialization/comments features, and cached dependency rlibs. No Cargo or full workspace build was run. This recovery environment has no compiler installed, so recovery is not a rerun.

## Actual observed outcome before reset

The deliberately selected typed matrix contained 1,574 observations per variant. Official 2.1.0 with the public compatibility settings differed from the legacy parser on 472; enabling the minimal local-tag policy differed on 312. It fixed 176 observations but introduced 16 additional mismatches. The same fork with its new option left at its default false produced byte-identical output to the official 2.1.0 matrix. This is an opt-in behavior check, not migration acceptance.

The unchanged expanded command/skill harness was **13 passed, 1 failed, 0 skipped** in both variants, each exit 101. A further 28 actual copied command/skill examples had 22 differences before and 20 after. Seven narrow policy/alias/budget controls passed. These passing controls do not override the compatibility failures.

Examples of remaining real behavior differences include:

- Legacy `String` accepts `!!int hello` as text; 2.1.0 rejects it.
- Legacy `u32` rejects `'1'` and block-style `1`; 2.1.0 accepts them.
- Legacy `Option<String>` yields `Some("null")` for `!str null`; the enabled local-tag policy yields `None`.
- Legacy `bool` rejects `!int 'true'`; the enabled policy accepts it.
- Bare `1e999`, explicit `!!float 1e999`, and a 128-bit integer beyond the dynamic Value's 64-bit capacity require three distinct legacy outcomes.
- Preserving all map entries requires a replacement semantic duplicate check for booleans, floats, radix integers, signed zero, NaNs, and composite map keys.
- Legacy `Value::as_str` and `as_mapping` unwrap tags; the initial wrapper misses tagged keys and tagged top-level mappings.
- Unknown global scalar tags, binary tags, and core tags on different node kinds still expose incompatible behavior.

A local tag-classification option and dynamic-number postprocessing do not cover typed target/style rules or pre-visitor rejection. Closing the migration would require a broader, independently qualified compatibility project involving typed scalar conversion, Value equality/accessors, node validation, all four real consumers, and retained error/resource tests. No new raw parser or opportunistic scalar schema layer was built here.

## Official dependency provenance

- serde-saphyr 2.1.0: <https://static.crates.io/crates/serde-saphyr/serde-saphyr-2.1.0.crate>
- Archive SHA256: `3f4dc2714fc5632417a6e979602d7044bad8f2880c63fc7217087180acec31b6`; 756,078 bytes.
- Package VCS commit: `38f420228cd783db25343cbe71ab90e806f0de30`; declared MSRV 1.89. The experiment was not an MSRV test.
- granit-parser 2.1.0 archive SHA256: `05f05586d4d4df3d47123207826c40b252728b438a1a07bad3c01ee6bea401df`; declared MSRV 1.81.0.

Only the small diff, self-written/reconstructed sources, observed summaries, and preserved tool output belong in this research archive. Official extracted trees, crate archives, compiled binaries, and large caches are excluded. Source hashes in the archive manifest describe the recovered archive bytes; they do not retroactively prove identities of lost execution inputs.

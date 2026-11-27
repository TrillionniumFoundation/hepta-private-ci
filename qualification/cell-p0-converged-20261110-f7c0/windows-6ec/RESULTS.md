# Exact-source Windows CI readback: 6ecfa504d2132f3682ffb01f8c9d65346b26cf5b

## Outcome and evidence boundary

The existing Windows workflow run [42937198409](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42937198409), attempt 1, and its only job [130250125460](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42937198409/job/130250125460) concluded SUCCESS. This bundle preserves the complete original artifact ZIP and complete tool-decoded job log. No CI, test, model, OCR, training, or business task was started or replayed to produce this readback.

This is Windows private-state, durable-owner, and selected Prompt Runtime qualification for the exact source below. It does not qualify the complete P0 learning chain, the separate Training pair adapter, all StageOwner callers, or any later source head. These are engineering tests, not independent confirmation tasks or measured policy gains.

## Source and native compiler

- Source head: `6ecfa504d2132f3682ffb01f8c9d65346b26cf5b`.
- Source tree: `9184583f3842d90a560436f279c753f15792e3ab`.
- Head provenance: original run metadata, complete job-log checkout and explicit HEAD check, and the original ZIP's `manifest.json`.
- Tree provenance: original run `head_commit.tree_id`, original ZIP `manifest.json`, and local read-only `git rev-parse <exact-head>^{tree}`. The job log does not itself print the tree digest.
- The ZIP's original positive production source is byte-identical to `git show <exact-head>:codex-rs/utils/path-utils/src/private_state_windows_directory.rs`.
- That source's SHA-256 is `21600c6d3b738afbd53db9fffd088944fb7fe1fbc947efde9520fc49e439e1ac`.
- Native compiler: Rust 1.96.0, commit `ac68faa20c58cbccd01ee7208bf3b6e93a7d7f96`, host `x86_64-pc-windows-msvc`, LLVM 22.1.2. The original manifest and job log agree.

Run metadata records creation at 2026-11-11T01:12:15Z and update at 2026-11-11T01:33:02Z. Those are workflow metadata timestamps, not CPU accounting. Complete training/search/communication/compute costs remain unmeasured here.

## Actual main nextest suites

Counts were read from this job's five original nextest summaries and cross-checked against each named PASS row, not copied from another source head.

| Package and exact filter | Passed | Failed | Nextest skipped |
|---|---:|---:|---:|
| `codex-utils-path`, `test(private_state_windows::)` | 15 | 0 | 5 |
| `codex-hepta-prompt-registry`, `test(durable::windows::tests::)` | 2 | 0 | 26 |
| `codex-hepta-contracts`, `test(final_use::store::windows::tests::)` | 3 | 0 | 147 |
| `codex-hepta-contracts`, `test(authority_lease::windows::tests::)` | 2 | 0 | 148 |
| `codex-hepta-agentd`, `test(prompt_runtime::tests::)` | 12 | 0 | 326 |

These are 34 selected successful test executions across five invocations. The skipped numbers describe each invocation's filter exclusions and overlap; they are not summed into a count of distinct untested cases. No JUnit file is included in this artifact. Exact commands, nextest run IDs, named tests, durations, and original log line references are retained in `CI_EVIDENCE.json`.

The Agentd suite includes real durable-owner reopening and Unknown/lost-ACK behavior in Prompt Runtime. It does not run a Training pair adapter introduced after this head.

## Format, attack proof, and source restoration

The format step succeeded with:

```text
cargo fmt --package codex-utils-path --package codex-hepta-prompt-registry --package codex-hepta-contracts --package codex-hepta-agentd -- --check
```

This is a check of the four named packages. Stable rustfmt reported that the nightly-only `imports_granularity = Item` setting was unavailable. No repository-wide format, cargo fix, generic bins check, or full daemon/shared/core suite is claimed.

The attack-proof step separately ran six Python helper unit tests successfully, then retained these three native lanes:

| Lane | Actual nextest result | Native evidence |
|---|---|---|
| Original positive source | 2 passed, 0 failed, 18 skipped; exit 0 | Substitution: swapped=true, denied=true, redirected=false. Creation: denied=true, created=false. |
| `unchecked-create` mutant | 1 passed, 1 failed, 18 skipped; exit 1 | Creation test failed as intended: denied=true, created=true. |
| `path-check-open` mutant | 1 passed, 1 failed, 18 skipped; exit 1 | Substitution test failed as intended: swapped=true, denied=false, redirected=true. |

The two mutant failures are the expected rejection evidence, not production failures. These lanes reuse the same two directory tests, including tests already selected in the main suite; they are not additional independent task confirmations. Full lane logs, exact mutated source bytes, patches, and their hashes remain in the original ZIP. Every recorded lane source, patch, and log hash was recomputed.

The original manifest records `qualified=true` and `restored=true`. The succeeding job step checks `git diff --check`, `git diff --exit-code`, and `git status --porcelain --untracked-files=no`, failing on any tracked change. Its original step metadata says SUCCESS. This establishes the checked tracked-source cleanliness after restoration; untracked artifact output is deliberately excluded.

## Artifact and complete log integrity

- Artifact ID: `13820071570`.
- Original ZIP size: **13,533 B**.
- Original ZIP SHA-256: `b5cd3b06015b9d1aef2ba721540b21fd0b1bf10ae4d566d48ef6ae6be5823273`, equal to the original GitHub artifact digest.
- All **9 ZIP members** passed CRC validation and have independently computed SHA-256 entries in `ARTIFACT_INDEX.json`.
- Complete decoded job log: **260,174 UTF-8 B**, **259,932 UTF-16 code units**, **3,297 CRLF pairs**, original leading BOM retained.
- Complete decoded log SHA-256: `f172b40f7d1f2e9effed39ddf9d2f4cad834072c30a0355b9f4373d0f986e1f2`.
- `job_130250125460.decoded.log.gz` is a deterministic gzip of that complete decoded log; decompression was checked against the retained bytes. This preserves the connector's decoded text and is not a claim about the original HTTP transport encoding.
- `RAW_EXCERPTS.txt.gz` is an explicitly numbered derivative with ANSI escapes removed for reading. The complete gzip is authoritative for log text.

`API_CAPTURE.json` preserves the original run/job/artifact metadata. `CI_EVIDENCE.json` contains the structured checks and scope. `MANIFEST.json` hashes every other delivered file. No temporary artifact download URL is retained.


The excerpt gzip is a lossless storage transform recorded in `MANIFEST.json`; its decompressed bytes and logical filename match the original delivery.

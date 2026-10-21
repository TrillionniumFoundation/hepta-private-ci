# Original blocking CI terminal evidence for source 48177153

This directory preserves complete connector-decoded job logs from original
blocking run `39583123088`, with the original job/step conclusions and exact
UTF-8 byte hashes in each companion JSON. It does not qualify a later source.

| Job | Original result | Observed scope |
| --- | --- | --- |
| 119194391962, macOS Intel test | cancelled | Original 60-minute budget elapsed while compiling; no preceding test failure in the decoded log. |
| 119194391884, macOS ARM Clippy | cancelled | Compiling Rust and V8; original cancellation is not a completed Clippy result. |
| 119194392011, Windows release | success | Original release build completed; artifact identity is recorded separately. |
| 119194392010, Windows test shard 1 | failure | Git wrapper-exit timeout; complete diagnostic retained. |
| 119194392016, Windows test shard 2 | failure | Complete native failures and first-panic index retained. |
| 119194391901, Windows test shard 3 | failure | Queue manual-idle race and Matrixd unsupported peer identity; first TUI attempt also failed before its original retry passed. |
| 119194391938, Windows test shard 4 | cancelled | Four distinct targets failed before cancellation: Operator Acceptance, Shadow Qualification, Exec Server filesystem, and Agentd terminal-cell owner. |
| 119194391999, macOS ARM test | cancelled | Eleven distinct targets failed before cancellation; 174 distinct first panics are indexed. The final progress record is incomplete. |
| 119194392031, Windows Clippy | cancelled | No preceding Rust error in the decoded log; compilation remained active. |
| 119194392047, macOS ARM release | cancelled | V8 C++ compilation remained active. |
| 119194391125, SDK | cancelled | Its Bazel dependency build remained active in V8 C++ compilation. |
| 119194391990, GNU/Linux Clippy | cancelled | Full original log retained; unfinished compilation is not a passed Clippy gate. |
| 119194391991, Linux musl test | cancelled | Full original log retained; unfinished compilation is not a passed test suite. |

The Windows shard-2 and later first-panic indexes are navigation aids, not
substitutes for their complete raw logs. A cancelled job can contain genuine
test failures; these must remain separate from unfinished compilation. The
recorded elapsed durations are consistent with the original job limits, but
the logs do not explicitly identify the cancellation initiator. No agent
cancelled or reran these jobs or changed their limits.

`windows-release-artifact.json` identifies the original 4,949,485-byte ZIP by
API ID, full SHA-256, verified member CRC, and member SHA-256. The complete ZIP
remains in the workspace evidence cache. It exceeds the unchanged repository
512,000-byte blob policy and is not represented here as a truncated archive.

## macOS Intel cancellation detail

Original run
[39583123088](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39583123088)
reported macOS Intel test job `119194391962` as `cancelled`, starting at
11:40:21 UTC and ending at 12:41:02 UTC on 2026-10-21. This record does not
represent a successful completed test lane.

The complete job log records checkout
`3c32bedb07239b0cbdb38d100836258165cae633`, the original merge of source
`48177153ad04605338c3a9a8dbd17defee9981bc` into base
`57636c7a17d4847eb5fd712409816fd040b4e90f`, with tree
`22e14fcd85f7a3f2c5dc8f3a1bdb17efc81b4d62`. Its sole emitted error is
`The operation was canceled.` The full log contains no `FAILED`, `FAIL:`,
`ERROR:` or Rust `error[E...]` diagnostic. Its last progress record shows
11,802 / 16,357 actions and 15 / 569 tests while still compiling Rust and V8
dependencies. Those progress counters do not establish a completed test result.

The exact source workflow, archived as `bazel-481.yml.raw`, sets the test job
limit to 60 minutes and `fail-fast: false`. The observed elapsed time is
consistent with that original limit; the decoded log does not explicitly
identify the cancellation initiator. The original API conclusion remains
`cancelled`. No agent cancelled or reran the job, and no workflow limit,
assertion or permission was changed.

The runner explicitly logged that the BuildBuddy key was unavailable and
selected local Bazel execution. This establishes the observed execution mode,
not the reason the credential was unavailable or proof that a particular
infrastructure change would complete the build within its original budget.

The XZ archive preserves the complete connector-decoded UTF-8 bytes, including
BOM and line endings. Its companion JSON records original job and step states,
raw byte count and SHA-256, and compressed byte count and SHA-256.
`analysis.json` records the exact checkout, original workflow hash, terminal
error and last progress. Other jobs in the same run were still executing at
this checkpoint and require their own actual terminal results.

# Original V8 canary cancellations: intermediate record

At 12:16:43 UTC on 2026-10-21, original run
[39583122999](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39583122999)
had nine cancelled build jobs and four builds still in progress. Its metadata
job and Windows x64 source-build job had succeeded. The fourteen-build matrix
was incomplete and was not qualified.

## Exact source and original results

All nine complete logs in this directory show checkout
`3c32bedb07239b0cbdb38d100836258165cae633`, the original GitHub merge for source
`48177153ad04605338c3a9a8dbd17defee9981bc` and base
`57636c7a17d4847eb5fd712409816fd040b4e90f`. Its tree is
`22e14fcd85f7a3f2c5dc8f3a1bdb17efc81b4d62`. These results do not qualify the
later advancing base or later continuation sources.

The original API conclusion is `cancelled`. Each of these nine complete logs
contains only one emitted error: `The operation was canceled.` The original
workflow sets a 90-minute job limit; each cancellation occurred near that
limit, after continuing compilation. This is consistent with the original
time limit, but the decoded logs do not explicitly identify the cancellation
initiator. The available connection does not expose the check-run annotation
endpoint. No agent requested cancellation or reran any of these jobs.

| Job | Variant and target | Last recorded Bazel progress |
| --- | --- | --- |
| 119171686607 | sandbox Windows ARM64, upstream Cargo source build | Cargo buffered the native build output |
| 119171686809 | sandbox macOS ARM64 | 14,179 / 14,794 actions |
| 119171686802 | release Linux musl ARM64 | 15,968 / 16,450 actions |
| 119171686915 | sandbox macOS x64 | 12,324 / 14,054 actions |
| 119171687001 | release macOS ARM64 | 13,978 / 14,794 actions |
| 119171686938 | release Linux GNU ARM64 | 14,957 / 15,123 actions |
| 119171687003 | sandbox Linux GNU ARM64 | 14,811 / 15,123 actions |
| 119171686852 | release macOS x64 | 12,571 / 14,054 actions |
| 119171686990 | sandbox Linux musl ARM64 | 15,892 / 16,450 actions |

Every listed job stopped in its original build step. Staging, Cargo smoke and
artifact upload were skipped. The complete logs contain no earlier emitted
compiler failure. Progress counters describe scheduled actions, not percentage
of remaining wall time or successful artifact qualification.

## Cold-build and cache observations

The Bazel logs report that the BuildBuddy key was unavailable and that local
Bazel execution was selected. The final progress records show about four
concurrent C++ actions. The Windows ARM64 upstream source cache was a miss,
and its cache post-step was skipped after cancellation.

The exact 481 `setup-bazel-ci` action supplies only `bazelisk-version` and
`output-base` to the pinned upstream setup action. The directly retrieved
[pinned upstream action](https://github.com/bazel-contrib/setup-bazel/blob/c5acdfb288317d0b5c0bbd7a396a3dc868bb0f86/action.yml)
defaults its disk, repository and Bazelisk Actions caches to disabled and has
`post-if: !cancelled()`. `cache-policy.json` records both source hashes and the
checked settings. On-runner `disk-cache` progress labels therefore do not prove
durable cache reuse between these jobs. No timeout, cache permission, credential,
matrix, build flag or qualification assertion was changed by this review.

## Preserved evidence

Each XZ file losslessly preserves the connector-decoded log encoded as UTF-8,
including its original BOM and line endings. Its companion JSON records raw
and compressed sizes and SHA-256 digests, original job identity and all steps.
`terminal-log-analysis.json` records each actual checkout SHA, emitted error,
last progress and skipped smoke. `intermediate-status.json` retains the whole
original matrix's observed status, with `qualification_complete=false`.

`v8-canary-481.yml.raw` contains the original workflow bytes; its companion
receipt verifies its hash and all three original timeout declarations. The
successful Windows x64 source-build log is already preserved under
`../ci-terminal-481-20261021/`; its POC step was a link-only `--no-run` smoke,
not a runtime POC test execution. Four remaining original V8 builds were still
running at this checkpoint and require their actual terminal results.

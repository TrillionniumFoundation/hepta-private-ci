# Engineering build history

These are byte-for-byte copies of the four prior build receipts and their
natural corresponding logs from `owner/runs/build01/`. They preserve engineering
setup evidence preceding the authoritative owner run. The final build receipt
and log remain in the parent directory. No binary or vendored dependency files
are included here.

| Recorded invocation | Recorded build wall seconds |
| --- | ---: |
| Initial offline build, previous.0 | 28.953136427 |
| Offline rebuild 1, previous.1 | 1.455495001 |
| Offline rebuild 2, previous.2 | 1.374504926 |
| Offline rebuild 3, previous.3 | 1.448072353 |
| Prior-invocation subtotal | 33.231208707 |
| Final offline rebuild, parent receipt | 1.859409300 |
| Recorded build-invocation subtotal including final | 35.090618007 |

## Timing scope

`build.py` starts its fresh-build timer immediately before Cargo execution,
after source copying, workspace/configuration preparation, registry downloads,
archive checksum verification, extraction, vendor-checksum preparation, and
research-source installation have completed. The timer includes Cargo and
immediate post-build identity inspection. It does not record the elapsed time of
those preceding preparation and dependency-acquisition operations.

For rebuilds, the timer similarly starts after pre-build integrity checks,
research-source copying, and preservation of earlier receipts/logs. Neither
receipt records build CPU time or the complete external process duration.
Toolchain installation, initial failed acquisition attempts, earlier environment
setup, and engineering test time are not reconstructed from file timestamps or
assigned invented durations.

The subtotal counts the five recorded build invocations once. It is not complete
setup wall time, a from-scratch build benchmark, or inference latency. The final
build is already reported in the formal stage-cost table: adding this subtotal
requires replacing that final-build row, not counting it twice. These engineering
iterations must not be added again to owner runtime or audit counters.

`cargo-build.previous.1.log` and `cargo-build.previous.3.log` have identical bytes; their
receipts identify distinct invocations and binary hashes. The archive uses a `cargo-build` prefix so plain logs are not mistaken for
Bazel `BUILD.*` source files. The original-to-archive name mapping and unchanged
byte hashes are recorded in `../LOG_NAMES.json`. Copies and log files are not
additional build executions.

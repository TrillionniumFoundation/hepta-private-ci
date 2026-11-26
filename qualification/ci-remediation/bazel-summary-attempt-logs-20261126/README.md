# Preserve explicitly reported Bazel summary logs

## Original evidence

The macOS Intel job `139664083831` on the `be271dd` source tree reported Core
library `FLAKY, failed in 3 out of 11`. Its full console log has SHA-256
`c6be0c55a2f68db2b58e5c1036d9e8dea58f44a8195c440b336a5e7cdec59771`.
Line 8995 contains an inline `FAIL:` path for shard 5. The `FLAKY: ... (Summary)`
block at lines 9831–9834 additionally names the first attempts of shards 8 and 4.
Those paths are repeated in the final target summary.

The original artifact `15084564486` has SHA-256
`f8055e48b0824b3ac4837f37e1fa36c9943df85906b4030b8a913686447085cc`.
It contains the complete shard-5 attempt but neither of the other two logs.
The collector only recognized inline `FAIL: ... (see ...)` paths. This proves a
parser coverage gap; it does not prove whether either missing file still existed
when the original collector ran, or reconstruct their missing contents.

## Change and limits

The collector also accepts explicit `FLAKY:` and `TIMEOUT:` headers and log paths
immediately following their target's `(Summary)` header. The summary state ends
at the first line that is not an indented test-log path. No directory scan or
inference from target names supplies additional files.

Existing path normalization, deduplication, per-path archive directories, and
`source-path.txt` attribution remain in place. Files are copied byte for byte;
Windows CRLF content is not normalized. Original console-tail selection and its
200-line limit remain unchanged. Archival after a successful invocation also
recognizes a summary-only failed attempt, without printing passing test logs.
The original Bazel exit status, targets, timeouts, and retries are unchanged.

The script controls cover the observed mixed inline/summary form, summary-only
success, Windows path spelling and CRLF, duplicate paths, a following unrelated
path, and a timeout summary on a failing invocation. They use a recording Bazel
fixture and real filesystem copies, not Rust execution. Actual CI archival of
future summary-only failures remains to be observed. The two old missing logs
remain unavailable.

The current script suite passed 92/92. The two new controls first failed against
the original collector, with those expected failures retained before restoring
the candidate. No Bazel build or Rust test was started for this change.

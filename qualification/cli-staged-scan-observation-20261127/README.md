# Observe the existing macOS staged-update scan

The original 1dd7 Intel test returned `None` where the first assertion expected
build 6268. Its original log does not report directory-scan errors, how many
bundles reached inspection, inspection results, or elapsed time. A shared
one-second deadline surrounds the real `plutil` inspections; that is a possible
boundary, not an observed historical expiry cause.

This candidate adds a per-scan observer only in macOS test builds. The existing
scanner still calls each filesystem operation and real inspector once, in the
same order. All three callers, both assertions, five bundle fixtures, 320
unrelated directories, symlink rejection, 64-bundle limit, and one-second
deadline remain unchanged. No inspector, command, timer, or return value is
replaced. Production builds contain no observer or diagnostic output.

Each test scan produces at most one libtest-captured scalar line. It records a
fixed phase, the number of directory entries pulled and bundles inspected,
I/O and inspector error counts, identity/build-result counts, the last I/O
stage and coarse error class plus raw OS code, and wall-clock elapsed times.
All counters saturate. The line includes no path, plist content, command
output, or dynamic error string. The longest scalar representation is bounded
independently of the number of cache entries. It is not a latency guarantee.

The observer is dropped on an early return or cancellation too. `tail_reached`
means execution reached the final original return expression; an in-progress
phase does not imply successful return. `latest` is meaningful as the returned
value only when that flag is true. Expected absent `extracted` directories
also contribute to I/O counts. The coarse `Other` I/O class intentionally does
not identify the exact error kind. An inspector error remains its original
collapsed `DiscoveryError`, so it does not by itself identify a failed `plutil`
spawn, exit, JSON parse, or invalid bundle metadata.

Libtest normally hides captured lines for passing cases. The original test
contains two scans and may therefore expose up to two lines if it later fails.
The second assertion is not assumed to have run in the historical failure.
The observations include scheduler and observer overhead and are not CPU time.

This is a diagnostic candidate. Formatting and source checks are not native
qualification, and no Rust test or external `plutil` command was run locally.

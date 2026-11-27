# Observe code-mode endpoint startup failures

The existing macOS Intel Bazel run contains code-mode endpoint startup failures.
Its 38 emitted failure records cover five target labels and include repeated
attempts; they are not 38 independent failures. The same job also passed stdio
and Unix-socket cases, so the record does not establish that the host executable
is universally broken. The host uses a current-thread Tokio runtime, and the
TCP listener binds before printing and flushing its endpoint.

This change adds a bounded observation only after the original endpoint read
has failed. It records the child's nonblocking `try_wait` result and performs
one poll of a stderr read into a fixed 4,096-byte buffer. A pending read is
reported as `not_ready_at_observation`, not as empty stderr. The escaped prefix
is a single observation, not the complete process log or proof of causality.

The shared `HostHarness` and the direct gRPC TCP test use the same helper. Their
original 10-second deadlines, loopback endpoint checks, process ownership,
`kill_on_drop`, and success paths remain. There is no added wait, sleep,
background task, retry, dependency, or production change. Existing timeout and
I/O errors remain in the error chain. A successful TCP read returning zero
bytes still reaches the original invalid-endpoint error; this candidate does
not claim to diagnose every possible startup failure. It also does not
instrument the separate stdio `ProcessOwned` provider.

The source observation is from job `139214394580` in run `45616349339`.
Its 1,876,725-byte log has SHA-256
`e63d41ea1043566e4e1de91bbdfb55d3f7bdfe925be71d962d63ffc0187a2ade`.
The executed merge tree equals source `4be2e45d4c90fe539abf61814fa9b362d8922881`.
This candidate is based on `4497d4b5029b8e1a39a670e780f1722a09edc909`.

`just fmt` and `git diff --check` pass. Independent source review verified the
unchanged deadlines and bounded failure-only observation. No new Rust build or
native execution has yet qualified this candidate, and this diagnostic alone
does not repair or close the original startup failures.

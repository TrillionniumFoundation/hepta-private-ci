# Observe existing stdio host stderr events

This is a test diagnostic, not a performance or handshake fix. No compilation,
native test, or CI retry has qualified this candidate.

The original macOS Intel job `139214394580` in run `45616349339` reports eight
stdio integration tests: four passed and four failed. All four failures occur
while creating the first remote session, with the existing error
`timed out negotiating with the code-mode host`. They do not reach their
scenario-specific large-payload, long-wait, or process-loss operations. The job
log is 1,876,725 bytes with SHA-256
`e63d41ea1043566e4e1de91bbdfb55d3f7bdfe925be71d962d63ffc0187a2ade`;
the relevant console section is lines 10078–10120. These are the original
results, not results of this candidate.

The process provider's existing 30-second timeout encloses both writing the
client hello and reading the host hello. Its original error does not identify
which operation was pending. The existing cleanup closes the writer and kills
and reaps the child before returning that error. This is a separate path from
the listener fixture's 10-second endpoint wait.

Production already consumes child stderr in a background reader and forwards
lines through tracing. The stdio test binary did not install a subscriber for
those events. A private test support module now observes only the exact
`codex_code_mode::remote_session::connection` target and the two existing stderr
forwarding/read-error message prefixes. No second pipe reader, background task,
production event, or production API is introduced.

The subscriber is process-wide so existing spawned Tokio tasks are observable.
Events can belong to any concurrent case. The report explicitly disclaims
case attribution; absence of captured events does not prove empty stderr,
child liveness, or a completed handshake phase. An existing global subscriber
is never replaced: installation conflict is reported as unavailable observation.

Formatting retains at most 1,024 bytes per event and 4,096 bytes across the
process, preserving UTF-8 boundaries. Capture and reporting use `try_lock`;
contention or poison does not wait or reset state. Only the first panicking
case's guard attempts a report, at most 4,096 bytes including its final newline.
Reporting failure does not replace the original panic. This is a bounded prefix
observation, not a complete transcript or an atomic snapshot of all tasks.

The eight original test bodies are byte-identical after removing the added
module declaration and observation guards. Assertions, providers, inputs,
timeouts, retries and cleanup remain unchanged. Cargo already declares both
tracing dependencies; Bazel already includes the test support source through
its `tests/**` compile data. No dependency or lock change is required.

`just fmt` and `git diff --check` pass. The original stdio suite must still run
under the normal qualification gates; this source review does not turn the
original four failures into passes or identify their underlying cause.

# Paired fixture initialization phase observation

## Retained observation

The normal Intel run at fixed `020f69a4479409ed88daf7a23a6caea1417de708`
retained 15 elapsed stage records before the existing 300-second target
timeout. In the five-pair scenario, `fixture_create_begin` was at 0 ms and
`fixture_create_complete` at 233,309 ms. The later warm-pair readiness
interval was 183 ms. The last record was `start_all_begin` at 240,574 ms;
the test did not reach its later adoption recovery in this output.

These are elapsed intervals on the existing process-wide monotonic clock,
not CPU measurements. The old output locates the large interval in
`PairFleet::new()` as a whole. It does not prove that release copying,
hashing, a filesystem operation, or initial recovery dominated that time.

## Change

Use the existing `trace_pair_stage` function unchanged. Add fixed begin
and completion labels around registry initialization, each agent
registration, the single release-bundle installation, each release
allowance and each binding write. Registration includes evaluation of its
existing manifest and workspace-binding arguments. Earlier temporary-root
creation and preparation between these calls remain outside their local
intervals. Repeated labels follow the original agent iteration order;
they add no IDs, paths, payloads, hashes or formatted error values.

Both existing `Supervisor::recover` calls retain the same arguments and
order. Hold each returned `Result`, write a fixed `returned` label, then
apply the original `?` and assertions. A `returned` label does not mean
success. It separates a returned error followed by caller cleanup from a
call that has not yet returned far enough to emit the label. Argument
preparation can also fail before that label, and a diagnostic write can
block or fail, so absence is not a unique root-cause determination.

The original 45 stage call sites retain their labels and order. The 13
new call sites execute at most 55 times across the existing two-agent and
five-agent scenarios: six fixed calls per fixture, six per registered
agent, and one later adoption-return call. There is no marker in a polling
loop or child process. The original clock, 128-byte stage writer, ignored
write errors and readiness-error writer remain byte-identical. Each stage
record remains at most 103 bytes for a full `u128` elapsed value. Byte
limits do not bound stderr latency or make the observation nonintrusive.

## Preserved contract and qualification

No process image, bundle content, hash or admission check is replaced or
skipped. There is no new wait, retry, deadline, clock, production hook,
dependency, lifecycle predicate or success assertion. All original
300-second target, 60/10/5-second fixture budgets and polling intervals,
process locks, release operations, child code and cleanup remain unchanged.
Removing the added markers and restoring the two original `Result`
bindings recovers the complete original fixture byte for byte.

The existing test module holds these precise call-site observations so
the original operations remain visible in order; no new helper or module
is needed. This is diagnostic source preparation only. Rust, native tests
and CI have not been run for this candidate, and the timeout remains open.
The per-agent internals of `start_all()` and warm-up release resolution
remain unobserved by this change.

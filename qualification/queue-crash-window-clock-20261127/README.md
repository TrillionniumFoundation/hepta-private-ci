# Queue crash-window fixture clock

The original Windows 1dd7 attempt failed before Core submission, at the
authorization CAS. It expected the later injected completion error. The
retained log does not contain the actual clock values or database row, so
it does not identify which CAS predicate rejected that attempt.

The existing fixture does impose an unrelated timing prerequisite: its
250 ms claim lease starts before the claim transaction, and authorization
samples wall time again after that transaction and an optional rollout
scan. Those operations and scheduling have no 250 ms bound. The renewal
UPDATE still requires the old expiry to exceed the authorization time.

This candidate fixes that fixture race using the timestamp parameters
already present in QueueStore. An optional per-instance shared clock in
FailDeleteOnceQueueStore remaps claim, authorization and expired recovery
to the same logical time while preserving each supplied window width.
The original 250 ms override remains in claim and authorization. Default
None returns the original time arguments unchanged for all other cases.
No production clock, SQL predicate, process lock or ownership rule changes.

The crash fixture freezes logical time at 1000 through the real admission
and injected completion failure. It keeps the original 300 ms sleep and
all original assertions. A reopened StateRuntime uses the same clock and
a fault-free wrapper with the original normal requested window widths.
Before advancing time, start must return DispatchInProgress and retain
the row without a second model request. This is the actual service order:
claim returns InFlight before the rollout reconciliation branch.
The clock then advances 300 ms; the original recovery, one-request and
one-durable-client-message assertions run unchanged.

An additional integration control calls real LocalQueueStore and SQLite
with independent fixtures: authorization at logical 1249 succeeds, while
logical 1250 fails at the exact 250 ms boundary. Deliberately different
caller timestamps exercise both clock mapping points. The existing
owner-lock, stale-revision and expired-rollout controls are unchanged.

This is a test-only clock for dispatch deadlines. State updated-at
bookkeeping retains its existing real-time source. The clock does not
accelerate Core, change any timeout, create rollout evidence, bypass the
OS lock, or authorize recovery from expiry alone. No dependency or API is
added. Authored controls and the modified fixture require native execution
in the normal qualification run; source review and formatter results do
not establish that execution or retrospectively prove the failed row.

## Caller cancellation fixture

The Intel 1dd7 report also failed while waiting for the blocking prompt
hook's entered file. Its 62.68 seconds is the whole 35-test target report,
not the hook's ten-second wait. The retained error does not include the
owner task's result, the SQLite row or the sampled time. It does not prove
that this specific attempt expired, or exclude a Core, hook or scheduling
failure. The same report passed the crash-window and hook-rejection cases.

This successor also selects the logical clock in the existing caller-abort
fixture. The short-lease owner and the fault-free competing store share
one clock at 1000 through the real hook entry. The original caller abort,
cancelled JoinHandle assertion and 400 ms sleep remain. Only after that
sleep does the clock advance to 1400, beyond the unchanged 1250 expiry.
The competitor must still fail with DispatchInProgress while the owned
Core dispatch holds the real process lock. Its normal requested window
width and every original one-request and persistence assertion remain.

If the original entered-file wait fails, an already-finished owner task
is joined once to report its actual Result; an unfinished task is only
reported as a snapshot and is neither awaited nor cancelled by this new
error branch. The original wait error stays in the error chain. No retry,
new timer or success-path wait is introduced. Diagnostic formatting and
the existing scheduler do not provide a hard real-time guarantee. A task
reported unfinished may finish later. This is a failure-only observation,
not proof that the detached Core task or any subprocess has stopped.

The original b67 candidate is retained unchanged. This successor keeps
its crash-window fixture, real SQL boundary control and default-None
behavior byte-for-byte. Neither version has been compiled or executed in
this source-preparation environment; normal native qualification remains
required for both modified fixtures and the authored SQL control.

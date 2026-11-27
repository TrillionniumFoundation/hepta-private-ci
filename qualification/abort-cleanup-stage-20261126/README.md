# Observe the retained abort cleanup stage

Base: `b25482def1253d79be1529329f13c54eea2d5e94`.

The original Windows unit-test attempt of
`resume_agent_from_rollout_reads_archived_rollout_path` failed its unchanged
five-second admission-fence wait. Its failure-only snapshot retained an abort
handoff in `TaskAborting`, with `failed_closed=true`, no quiescence result, and
no terminal persistence generation. The snapshot did not identify the nested
await, so it cannot distinguish interruption, task cleanup, rollout persistence,
timing state, or final event publication.

An enum now records the last entered stage directly in the existing abort
handoff. The existing nonblocking failure snapshot reads this enum after an
owner returns its witness. The small enum lives in a separate module; assignments
remain beside the awaits they describe to preserve the exact cleanup order.
The unstarted-turn path uses the same method with a local diagnostic value; it
does not gain a persistent running-task handoff.

No control-flow branch reads the enum. No observer is registered earlier, and no
new authority, task, lock, event, background job, or wait is retained. The normal
30-second and unit-test two-second watchdogs, both 100ms task waits, fixture
five-second wait, fail-closed ownership, and all original assertions stay
unchanged. Existing output fields are retained; one fixed-label diagnostic field
is added to the abort handoff snapshot.

This is diagnostic coverage, not a repair or a new passing native test. It adds
no retry or permission to reopen a failed-closed admission fence. The enum names
the last entered stage, not a completed stage, CPU time, or a causal proof of the
original failure. Normal CI must still exercise the existing test.

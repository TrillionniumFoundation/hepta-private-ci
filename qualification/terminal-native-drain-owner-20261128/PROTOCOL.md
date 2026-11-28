# Terminal native drain owner qualification (prospective)

Frozen parent: `6eba6064ab0bed37ba5fe4654c7596bc18088b9b`.
This is a repair of one previously failing engineering control, not a new
training experiment. It performs zero native fits and reads no science cache.

## Preserved history

The original e333 28-control command reached its 240-second cap: 19 named
passes, three named failures, six without a terminal result. Its raw log SHA256
is `7cdb73e95a8da1e0e6b33ebb5c51fcbcde82fa2f7b166b2fb72651ba619d459d`.
The first draining failure was a repeated exclusive prompt-owner fixture open.
The 6eba remaining-nine command then completed with eight passes and this sole
draining failure at its Pending assertion. Its raw log SHA256 is
`64de4195a0aeb2b753fbb5a49ab677a0f623877920b9bfe44870979e3cf4ee65`.
That assertion did not print the returned Ready value; its Ok/Err classification
was not observed. Neither original receipt may be rewritten as a passing gate.

## Source diagnosis and repair

At the fixed parent, `state_circuit_task.rs::circuit_task_drain_blockers` refuses
a missing AutomationStore before checking terminal blockers. The minimal test
fixture has no such store; the existing runtime drain test explicitly opens
and attaches a real AutomationStore. This is a source-level diagnosis, to be
tested here, not a claim that the unprinted prior error was observed.

Only the failed test acquires that existing real SQLite owner in its own
fixture layout and confirms zero Circuit blockers. The production Rust
lifetime file gains only cfg(test) observation state: one AtomicUsize field,
initialization, and increment at the original blockers predicate. Release
compilation behavior is unchanged; the Rust source bytes are changed.

After the real blocking worker reaches its existing before-fit barrier, the
test samples the predicate counter once. It then polls the SAME drain future
under a five-second timeout, with no other blocker reads in that interval.
Every Ready(Ok or Err) fails and prints the actual result. The synchronization
finishes only when a poll remains Pending AND the real terminal predicate was
observed after the sample. SQLite I/O alone cannot satisfy this condition.
The existing blocked-worker count, closed admission, undrained snapshot,
late/sticky attachment refusals, worker release, successful completion of the
same drain future, released Ledger lock, and zero-fit checks are retained.
No sleeps, fake clock, new production helper, or authority bypass is added.

## Exact eligible control and immutable budget

Only this fully qualified existing test may execute:
`plasticity_runtime::lifetime_tests::terminal_learning_tests::native_lifetime_tests::draining_closes_native_admission_and_cannot_finish_with_live_worker`.

The other 27 already passing controls are excluded. The original before-fit
barrier remains ten seconds; existing waits remain five seconds. The new
predicate synchronization uses five seconds and does not extend those waits.

The same exclusive native owner runs this one test through the repository's
existing just/nextest route, after actual just fmt and exact source freeze.
The command cap is 145 seconds, with 66 seconds reserved for wrapper cleanup.
The once-scoped just fix cap is separately 220 seconds plus 66 wrapper seconds.
Both are charged to the SAME original 3600-second engineering pool. Before this
gate, actual cumulative usage is 3102.1593757750616 seconds and remaining budget
is 497.8406242249384 seconds. No budget is reset or borrowed from old science.

Preserve exact source hashes, command, test name, raw stdout/stderr, exit status,
elapsed monotonic time and cleanup/reap outcome. A source refusal, compile
failure, timeout, or missing final test result is not a pass. No automatic
retry or repeated passing control is authorized by this protocol.

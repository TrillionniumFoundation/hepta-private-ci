# Observe queue persistence after a resumed turn

The original Intel macOS artifact at source
`97ab00451799667faebac2c455a1e3176ebc90cb` contains one failed queue-service
attempt: 34 cases passed and
`externally_changed_queues_dispatch_independently_and_retry_failed_wakes`
failed immediately after observing the resumed thread's `TurnComplete` event.
The failed assertion requires the real SQLite queue to be empty. The complete
original log is retained; this proposal does not claim a reproduced interleaving.

The source does not make `TurnComplete` a queue-store completion barrier.
`run_owned_dispatch` waits for Core's persisted admission, then awaits a separate
task that completes the queue binding. `complete_owned_dispatch` emits the
existing `ThreadQueueChanged` event after the store operation returns. The
read-only `list` operation does not take the dispatch lock. These operations
permit the test to observe the Core event before the queue task has committed.

Only the affected fixture replaces its no-op event sink with a bounded
32-entry broadcast of thread identifiers. It subscribes before ordinary resume
and retains the original `TurnComplete` wait. It then observes the real queue;
when the row is still present, another observation requires an existing change
event for that same thread. Discovery notifications can precede completion,
so the event itself never substitutes for checking persisted queue state.
Lag or receive errors fail the test rather than dropping observations silently.

One absolute deadline covers both the turn wait and the queue-state observation,
reusing the original 25-second value. The original helper resets that timeout
for each next event; the new outer deadline is a stricter total bound, not an
existing total-turn guarantee. The original final empty assertion and all three
exact model prompts remain unchanged. The other waits,
external writer, skipped first wake, independent thread, shutdown, resume and
original two eleven-second fixture sleeps remain unchanged. The observer never
wakes, submits, reconciles, deletes, or otherwise drives the queue. It adds no
timer polling, retry, production hook, or deadline extension.

This repairs an unsupported ordering assumption in the test. It does not prove
that the original CI failure had no additional cause, and it does not qualify
queue durability. Formatting and source checks are separate from Rust and
native qualification, which remain pending for this source change.

# Wait for fixture-owned thread completion

The existing fork fixtures submit a shutdown operation to their parent thread
and then return. Submission confirms queue admission; it does not wait for the
session loop to terminate. The sender-route reload fixture already stops its
initial child before reloading, but it returns after its original assertions
without stopping the reloaded child or its root thread.

This test-only change uses the existing `CodexThread::shutdown_and_wait` method
at those three completion boundaries. Both fork fixtures keep their existing
child shutdown and termination wait before waiting for the parent. The reload
fixture stops the exact `reloaded_child` instance and then the root held in
`parent_thread`. It does not use the old, already-stopped child handle, remove a
registry entry, or change residency bookkeeping. The nested-parent reload route
is unchanged.

All existing assertions run before the added completion waits. The fourth
reported case, `resume_agent_restores_closed_agent_and_accepts_send_input`, is
unchanged: both of its existing `shutdown_live_agent` calls already wait for
actual session-loop termination. No timeout, retry, sleep, polling loop, input,
model, permission, production code or test selection changes.

## Evidence boundary

The original Intel Core job for `eb294db1b084746d3f24ae4a07c7a0d3b1bf8e19`
contains four timed-out attempts across three of eight shards. Each retained
log has one test without a terminal result. One log also prints a separate
failed test, but the shard timeout prevents the normal failure-detail section
from being emitted. The compact execution log distinguishes twelve actual
test-setup actions from twelve XML-generation actions; the four timeout actions
retain the original 900-second limit. Later retries belong to that original CI.

The inspected fixture and lifecycle source is unchanged at the preparation base
`c2326de0631f27aee7178dcdf549f34e73c9b9dc`. The incomplete ownership boundaries
are source-proven fixture issues. They do not establish which await or runtime
phase caused those timeouts, recover the missing panic, or explain the fourth
case that already joins its session. This candidate has no new native execution
and does not claim that the original timeouts are fixed.

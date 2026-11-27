# Synchronize the startup-hook fixture with its child request

Base: `b25482def1253d79be1529329f13c54eea2d5e94`.

The original Windows shard-4 attempt failed because only one UserPromptSubmit
log entry was visible. Its trace contains a parent request, a parent tool-result
follow-up, and a later child request with the expected SubagentStart context.
It does not contain the child hook completion result or the precise instant at
which the test's request wait returned.

`mount_sse_once_match` installs its recorder before its final route matcher.
That recorder can therefore contain a parent request even when the child route
does not match it. A nonempty recorder is not a child-request completion fence.
This case now uses the existing `wait_for_child_request`, which requires the
child prompt and rejects the parent spawn call. It also explicitly asserts that
the observed child request includes the expected startup-hook context.

The existing two-second request wait, hook-log waits, hook commands, trust
configuration, exact log cardinalities, identities, and all original assertions
are retained. No new polling loop, sleep, retry, handler, production change, or
deadline increase is introduced. The original failed attempt remains failed.

This corrects the synchronization predicate, not a proven hook execution fault.
Normal CI must execute the original case. Slow child startup or a failed child
hook can still fail it and must not be hidden by increasing the fixture budget.

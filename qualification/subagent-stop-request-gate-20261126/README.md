# Wait for the matching child request before checking stop hooks

## Retained native failure

On the Windows fourth shard at source
`be271ddfa2a2d519a44112e4f176d2d8c3499c25`, the original
`subagent_stop_replaces_stop_and_skips_internal_subagents` attempt failed its
two-hook-log-entry assertion with zero entries. Its bounded failure observation
found the child running and a `HookStarted` event for SubagentStop. It did not
observe completion. The complete 203,238-byte failed-attempt log is retained,
SHA-256 `5bc55bffa984c0fe1014d900a574fc49e5b382c1e3c615677a1a3e5f20f9967a`.
The eventual target pass after the original retries does not erase this failure.

## Fixture synchronization defect

`ResponseMock::matches` records a request and returns true. `base_mock` places
that recorder before the additional matcher supplied to `mount_sse_once_match`.
The recorder can therefore contain a parent request that fails the child mock's
last matcher. The previous two `wait_for_requests` calls checked only whether
each recorder was nonempty, so neither proved that the corresponding child
request had been received.

The two waiting points now require the respective child prompt or stop
continuation and exclude the parent's spawn-call ID, matching the existing
child-response predicates. The first wait and second wait each retain their
original two-second limit and ten-millisecond polling interval. All other
callers and the shared mock implementation stay unchanged. The subsequent
two-second hook-log wait, exact two-entry assertions, internal-agent exclusion
checks and bounded failure observation also stay unchanged.

This establishes a request-received synchronization point, not response delivery,
child completion or hook completion. The later hook-log checks still establish
the behavior being tested. The original failure log does not prove every source
of hook latency, and this correction has no native qualification before its own
source revision is compiled and tested.

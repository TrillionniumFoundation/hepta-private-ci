# Subagent failure diagnostics

Windows source `fac3c71755e688edd7df3c2bd60a5739aeaa2c57`, job
`139157914105`, recorded one SubagentStop attempt with only one of two
required hook entries. That shard passed an original retry. The encrypted
spawn case passed two attempts but missed its required communication logs
on another attempt; the child message and request assertions had completed.
The original failures remain failures. Neither observation proves a
particular scheduler, Python startup, or tracing-dispatch defect.

This diagnostic change runs only after an existing assertion deadline has
failed. A hook timeout reports the already-read hook-event/active-state
pairs, without rereading the file or exposing message contents. A spawn-log
timeout uses a nonblocking lock to report buffer size, line count, up to eight bounded
communication lines, and the target's enabled state at inspection time.
That enabled state does not establish its value when a prior event ran.
There is no probe event that could satisfy the required send/receive pair.

The original two-second hook wait, five-second logging wait, polling
intervals, retry policy, hook execution, wire contents and complete
send/receive correlation assertions remain unchanged. No production source
or tracing subscription is modified. This is observability for the next
original qualification run, not a repair or a new passing test result.

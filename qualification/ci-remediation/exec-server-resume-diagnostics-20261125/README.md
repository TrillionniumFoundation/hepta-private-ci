# Detached-session failure diagnostics

The Windows shard for PR #7070 at source `62527854d589f814144008579c6f5ecc0fe44d18`
reported `exec_server_resumes_detached_session_without_killing_processes` failing
with `timed out waiting for exec-server websocket event`. Its process-test target
reported five passes and one failure in 6.31 seconds. The later log-tail copy is
the same observation, not another execution.

- Workflow: `45592595521`; job: `139132610485`.
- Original log: 3,149,390 bytes; SHA-256
  `0e0a1d7f50bef0dfeb0c39d59e48a884a858c15522a5c61a56c71792a414b606`.
- The original test made five response waits without identifying the failing
  phase. A same-ID JSON-RPC error did not satisfy their predicates and was
  discarded before the generic timeout.

This change reports a same-ID error immediately and names each of those five
phases. It preserves the original event timeout, request bodies, disconnect and
reconnect sequence, and all session-identity and process-liveness assertions.
It adds no retry, delay, production hook or production behavior change.

Source inspection identifies a possible close/detach race: transport closure
and handler cleanup are separate, and the registry can reject an overlapping
attachment. The original log does not identify an error code or the failing
phase, so that explanation remains a hypothesis. A close frame is not treated
as proof that handler cleanup and session detachment finished.

Formatting and diff checks passed. This diagnostic candidate has not yet been
executed by the native test target and does not close the underlying failure.

# Browser worker channel and process recovery

This guide describes `SubprocessBrowserDriver`, not a replacement executor,
resource ledger, authority issuer or operation journal. The existing
`BrowserProfileHost` final-use and durable-effect rules remain authoritative.
Worker replies and process exit never authorize replay of an unknown effect.

## Transport admission and bounds

`worker-client.js` is the extracted private implementation of the existing
worker pipe client. The first malformed/replayed/cross-generation response,
unknown request, stream error/EOF, write failure or diagnostic overflow poisons
that exact channel. Poisoning rejects pending calls and blocks all later writes;
it does not wait for a process exit event to close admission. There is no new
worker, automatic retry, synthesized task outcome or returned authority.

Frames retain the unchanged worker V1 schema and canonical JSON/digest rules.
The decoder copies fragments once into a bounded body, rejects malformed UTF-8,
latches parse failure and EOF, and validates a whole input batch before exposing
its prefix. A response batch is fully checked before resolving any request.
A duplicate or invalid outgoing frame does not spend an output sequence.

Concrete transport bounds are one MiB per frame, 64 decoded frames per input
batch, four maximum frames per input chunk, eight pending requests/writes, four
MiB outstanding output bytes, 1024 abandoned request IDs and 16 KiB diagnostic
bytes per process. Diagnostic bytes are drained and counted, not retained or
published. Cancellation of a dispatched call keeps a bounded response tombstone;
a late callback cannot settle or dispatch a different call with the same ID.
These bounds are not a target-host throughput or memory-isolation measurement.

## Startup and retirement

Startup snapshots and validates the complete input before awaiting artifact
reads. Concurrent starts reject before acquiring files or a second child. An
already-cancelled start performs no file or process work. The verified private
artifact copy, process handle and profile directory remain one owned lifecycle.
A failed startup cannot forget a child merely because kill was requested.

`worker-process.js` records actual `exit` and `close` events on the original
ChildProcess object. A signal result, worker `stopped` acknowledgment or the
`killed` flag is not retirement. Failed spawn is distinguished from exited child;
a signal error on a launched PID is not reclassified as failed spawn. Normal
retirement requires observed child exit AND closed stdio; failed spawn requires
its close event. Signal retries use the same object, never a bare numeric PID.

Stop protocol wait and each cleanup wait are separately bounded to one second.
Caller cancellation can shorten them. Timeout, denied signal or cancellation
keeps the handle and profile owned and disallows new effects/startup. Repeating
`stop` with the same profile/generation/process identity is cleanup-only: it does
not send another stop frame or browser operation. File removal occurs after
physical observation; a removal error also preserves the path and lifecycle for
reconciliation. Successful cleanup permits a new, strictly later generation.

The driver retains the latest retirement receipt/generation per profile, for at
most 1024 distinct profiles. It rejects new-profile admission at capacity rather
than forgetting a frontier. A repeated retained stop is historical observation
and cannot touch a later live child. These frontiers are process-local and do
not replace the durable owner's longer history, crash recovery or authorization.
A new driver object is not permission to reuse an old operation/generation.

## Evidence limits and recovery obligations

`stopped: true` from this driver requires its local process/profile cleanup;
`directChildExited`, `stdioClosed` and `spawnFailed` report separate observations.
`descendantExitVerified` remains false. This is not escaped-descendant containment,
device-memory settlement, host-crash recovery, user-task success or permission to
close an indeterminate durable effect. The existing host continues to reject
profile close while its journal contains unresolved browser operations.

The full regression entry point remains:

```sh
node --test apps/hepta-browser/test/*.test.js
```

`worker-channel-failures.test.js` and `worker-decoder-bounds.test.js` cover actual
host code with controlled streams, corruption, replay and capacity cases.
`worker-retirement.test.js` covers signal denial, cancellation, retained cleanup,
concurrent lifecycle calls, immutable startup and generation frontiers; it also
launches an actual Node child and waits for real exit/stdio closure. That child
speaks a synthetic protocol: it is not Servo, a real browser task, independent
terminal observation, qualified Bubblewrap isolation or structural organ handoff.

Native Agentd checks, exact-source/fixed-main-merge execution, resident Laya's
protected native consumer, real authorized-data benefit and stateful multi-organ
migrations remain separate A-E acceptance obligations. No completion flags,
required checks, production model selection or effect authority are changed here.

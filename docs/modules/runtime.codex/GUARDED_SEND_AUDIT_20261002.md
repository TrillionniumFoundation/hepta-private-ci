# runtime.codex guarded physical-send audit, 2026-10-02

## Scope and source boundary

This additive stage follows the ordinary V2 retained-history candidate at
`82c6e2872dd835b3196e85f3ef381453a5488d1e`. It modifies the existing App Server
remote command writer and its named native inference caller. It does not copy
construction candidate `975` or integration candidate `6000`, introduce a second
execution engine, grant authority, or merge those divergent owner compositions.

## Source-confirmed defect

The native caller previously entered its final-use token before enqueueing a
remote command. The command writer neither checked the caller's continued
interest nor carried the request's deadline through socket readiness. Dropping
the caller's timed-out future did not cancel its queued command. Separately,
`run_once` created a new execution timeout after preparatory awaits and did not
clip that deadline to the verified plan's validity ceiling.

## Implemented source

- `NativeExecutionDeadline` captures a monotonic budget before admission awaits
  and clips the absolute deadline to `VerifiedExecutionPlan::valid_until_unix_ms`.
  The adapter intent/durable dispatch bind that absolute value. The live send and
  terminal observation retain the original monotonic ceiling, including across a
  wall-clock rollback during the invocation.
- The existing bounded remote command queue accepts an optional one-shot guard.
  Ordinary unguarded client APIs retain their prior semantics. The additive
  guarded observed-response API requires a guard rather than accepting `None`.
- The sole transport writer serializes the request, awaits sink readiness, then
  obtains fresh cognitive and Agentd health/ingress observations. Abandonment,
  cancellation and the original monotonic deadline race preparation/readiness.
- The final synchronous closure rechecks cancellation, the absolute ceiling,
  owner observations and the non-constructible final-use token. There is no await
  between entry and `start_send`; cancellation/abandonment and the monotonic
  deadline are checked again after a potentially slow entry callback.
- The entry value is retained through flush. Flush is also bounded, but every
  failure after `start_send` remains potentially dispatched. There is no retry.
  Any write/guard failure closes this client connection through the existing
  worker failure path.

Preparation runs inside the existing transport command owner, not the inference
journal writer. It must use independent owner channels and cannot await another
request queued on that same App Server client.

## No-effect and completion limits

This stage deliberately does not add a serializable or forgeable `NotDispatched`
flag. The caller drops its local pre-effect abort capability before enqueueing.
Guard rejection, queue timeout, future abandonment and lost acknowledgements
therefore remain reconcile-only and retain the durable reservation. They do not
become a release permit, and a fresh request identity is not recovery.

The guard's cut is admission to the WebSocket sink, not completion of a packet on
an external network. Async owner health and ingress observations are not an
atomic cross-process generation lease. A server ingress fence or owner-issued
live permit, the ordinary Agentd exact durable dispatch/abort/outbox bridge, and
crash/lost-ACK integration still require their separately owned composition.
A monotonic timestamp is process-local and is not manufactured across restart.
The existing durable absolute correlation/reconciliation boundary remains.

## Verification boundary

The source includes fake-sink adversarial tests for expired/abandoned queued
work, stalled readiness, cancelled preparation, denied authority, expiry and
cancellation inside entry, flush failure/stall and exactly-one entry/send.
Real WebSocket frames over an in-memory duplex exercise the actual remote worker
queue: expired guarded work and abandoned guarded work never arrive, while
legacy abandoned work retains its historical delivery behavior. Deadline tests
cover signed-ceiling clipping, shorter operation budgets and expired/zero budgets.

Full package compilation and test outcomes are recorded in the accompanying
qualification evidence rather than inferred from source-test existence. These
checks do not establish real Agentd/provider product execution, Windows runtime,
selected-host SLOs, exact-head/current-main-merge gates or independent acceptance.
All activation, promotion and release gates remain false.

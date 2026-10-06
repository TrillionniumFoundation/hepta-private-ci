# codex-app-server-client

Shared in-process app-server client used by conversational CLI surfaces:

- `codex-exec`
- `codex-tui`

## Purpose

This crate centralizes startup and lifecycle management for an in-process
`codex-app-server` runtime, so CLI clients do not need to duplicate:

- app-server bootstrap and initialize handshake
- in-memory request/event transport wiring
- lifecycle orchestration around caller-provided startup identity
- graceful shutdown behavior

## Startup identity

Callers pass both the app-server `SessionSource` and the initialize
`client_info.name` explicitly when starting the facade.

That keeps thread metadata (for example in `thread/list` and `thread/read`)
aligned with the originating runtime without baking TUI/exec-specific policy
into the shared client layer.

## Transport model

The in-process path uses typed channels:

- client -> server: `ClientRequest` / `ClientNotification`
- server -> client: `InProcessServerEvent`
  - `ServerRequest`
  - `ServerNotification`
  - `LegacyNotification`

JSON serialization is still used at external transport boundaries
(stdio/websocket), but the in-process hot path is typed.

Typed requests still receive app-server responses through the JSON-RPC
result envelope internally. That is intentional: the in-process path is
meant to preserve app-server semantics while removing the process
boundary, not to introduce a second response contract.

## Bootstrap behavior

The client facade starts an already-initialized in-process runtime, but
thread bootstrap still follows normal app-server flow:

- caller sends `thread/start` or `thread/resume`
- app-server returns the immediate typed response
- richer session metadata may arrive later as a `SessionConfigured`
  legacy event

Surfaces such as TUI and exec may therefore need a short bootstrap
phase where they reconcile startup response data with later events.

## Backpressure and shutdown

- Command queues and the embedded runtime remain bounded, using
  `DEFAULT_IN_PROCESS_CHANNEL_CAPACITY` by default.
- The facade's local consumer event queue is unbounded and preserves notification
  order. This keeps the worker draining the bounded runtime while a caller waits
  for a request, preventing unread notifications from blocking its response.
- `shutdown()` performs a bounded graceful shutdown and then aborts if timeout
  is exceeded.

### Remote request capacity

A remote connection retains at most 1,024 unanswered outgoing requests. A new
request at capacity fails locally with `io::ErrorKind::WouldBlock` before any
part of that request is written. An ID already pending still produces
`InvalidInput`, including at capacity, and never replaces the original waiter.
The existing bounded command queue retains its enqueue backpressure and FIFO
send order; the capacity check runs when the worker dequeues a request.

Dropping or timing out a response future does not free a sent request's slot or
ID: the peer might still execute it and reply later. Matching responses and
errors free slots before waking waiters. If replies never arrive, slots remain
occupied until the connection exits. The owner may choose to close the shared
connection, which also fails unrelated pending requests. There is no automatic
close, resend, cancellation, or retry policy.

Control and cancellation RPCs use the same outgoing request budget and can be
rejected at capacity. Notifications, replies to server requests, and explicit
shutdown do not consume slots, but still use the existing command queue and
transport. The cap does not give them priority or a new shutdown time bound.

This bounds request count, not payload/ID bytes, execution time, caller-created
futures waiting to enqueue, or event-buffer memory. With command capacity `M`,
there are at most `1,024 + M` pending/queued registrations plus one dequeued
transient command. Initialization occurs before this budget exists. Sustained
loads requiring over 1,024 concurrent unanswered requests now receive local
capacity errors; callers should handle that explicitly without treating a
separate timed-out request as absent or safe to repeat.

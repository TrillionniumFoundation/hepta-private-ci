# Code-mode host startup phase observations

This change adds observations for the next normal CI execution. It does not fix
or qualify the reported startup timeouts.

The original macOS Intel run had 28 failures across four integration targets:
9 gRPC, 4 gRPC notification, 4 gRPC TCP, and 11 WebSocket cases. Each failure
reported that the child was still running after the existing ten-second endpoint
wait. The later single nonblocking stderr read returned `WouldBlock` (OS error
35). The gRPC target also passed six cases that started the same kind of child;
its other two passing cases did not establish that child-startup control.
The same four targets passed in the GNU job without a cache label. Their musl
results were cached and do not establish another independent execution.

## Added observations

The existing INFO subscriber and stderr writer record a fixed phase label and
monotonic elapsed milliseconds. No new field contains a listen address, path,
argument value, prompt, image, credential, or other user content.

| Clock | Phase | Observed boundary |
| --- | --- | --- |
| Async main body entry | `tracing_ready` | Existing subscriber initialization returned |
| Async main body entry | `arguments_ready` | The original single argument parse returned |
| gRPC listener entry | `grpc_bind_begin` | About to execute the original bind await |
| gRPC listener entry | `grpc_listener_bound` | The original bind succeeded |
| gRPC listener entry | `grpc_endpoint_published` | The original endpoint stdout flush succeeded |
| WebSocket listener entry | `websocket_bind_begin` | About to execute the original bind await |
| WebSocket listener entry | `websocket_listener_bound` | The original bind succeeded |
| WebSocket listener entry | `websocket_endpoint_published` | The original endpoint stdout flush succeeded |

The main and listener clocks have separate origins. Do not subtract their
elapsed values from one another. A published phase confirms the child's flush
result, not that the parent received the endpoint.

## Preserved behavior and limits

Argument parsing, binding, endpoint output, flush errors, listener construction,
and serving retain their existing order. There is no new await, subscriber,
dependency, background reader, retry, or runtime. The existing tests, ten-second
wait, stderr read and display bounds, pipe flags, and assertions are unchanged.
The earlier listener-address messages remain unchanged.

The first event occurs after the Tokio runtime and tracing subscriber have been
constructed. If no event is captured, loader or static initialization before
main, runtime construction, subscriber initialization, and scheduling remain
unresolved. Explicit session and V8 initialization follow endpoint publication;
this does not rule out work performed before main by the loader or static
initializers.

Elapsed time is wall time, not CPU attribution. Existing synchronous logging
adds observation overhead and is not guaranteed to complete within a time
bound. The failure reader still displays only its original bounded prefix;
truncation or a later event cannot be treated as evidence that a phase did not
occur. Child status and stderr remain separate, non-atomic observations.

Validation for this candidate is source review, formatting, spelling, and
preservation checks only. No Rust build, native startup, or test rerun is claimed.

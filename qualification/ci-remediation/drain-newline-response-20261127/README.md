# Preserve a completed Agentd drain response

The paired-process ARM test on source `098e68431bedcb040a04a96daeefcade9e45be68`
reported `Socket is not connected (os error 57)` after the two-pair restart
completed and the replacement wait began. The five-pair scenario completed.
The original failure does not identify which socket operation returned the
error. It does not prove a new timeout, a damaged generation fence, or a peer
restart.

The drain client currently sends one complete newline JSON frame, performs
`shutdown(Write)`, then reads one response. Both the production Agentd server
and the controlled paired child consume a bounded newline request; they do not
need request EOF. A peer can finish and close after sending its reply. The
optional client half-close is then an extra fallible operation before that
reply can be read. Apple's `shutdown(2)` documentation lists `ENOTCONN` for a
socket that is no longer connected. This is a possible failure mechanism, not
an observed syscall trace for the original CI failure.

This candidate removes that extra operation from the drain exchange. It still
requires a complete bounded newline response and the exact schema, request ID,
agent ID, spawn/current generations, draining lifecycle, admission closure,
fence state, and zero running turns. A missing response is never a successful
drain acknowledgement. The existing incomplete-error classification, 200 ms
I/O limits, lifecycle deadlines, stop/kill behavior, restart budgets and all
paired-process assertions stay unchanged.

The existing drain code moves into a private sibling module because `unix.rs`
already exceeded 800 lines. The new module uses the existing crate dependency
and Bazel source glob. The three original sibling controls remain, with the
same bodies. Three additional controls cover a complete reply whose peer has
already closed, rejection of incomplete/malformed/wrong-generation replies in
that same state, and retention of the original error kind and errno when
transport-stage context is attached. The closed-peer controls use a socket
pair with the response written before the read; they need no thread scheduling,
sleep, retry or process fixture to reach that state.

The error context names connect, read/write timeout setup, request write, or
response read. It retains the original `io::Error` as a source and uses its
unchanged `ErrorKind` for classification. It does not add `NotConnected` to the
incomplete-error branch or convert an unverified reply to success. Other
health-probe exchanges are outside this change.

This is source preparation. The three new Rust controls, all original drain
controls, and the native paired lifecycle still need exact-source qualification.
A formatted diff or a passing source review cannot establish that the observed
ARM failure is repaired. Preserve the original failure, check the natural CI
result, and keep the blocker open if any error or fence assertion remains.

Primary API reference:
<https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/shutdown.2.html>.

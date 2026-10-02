# Adopted process lifetime and signal binding

This is an implementation amendment to `TECHNICAL.md`, not a target-host or
release acceptance receipt. The native Rust tests named below must execute on
the exact source and deterministic merge candidates before this change is
qualified. Existing production authority and writer boundaries are unchanged.

Original source-only checkpoints below are historical observations. Later native
outcomes are recorded in the
[R3 local observation](../../../qualification/runtime-supervisor/LOCAL_EXECUTION_OBSERVATION_20261001_R3.json)
and [R4 local observation](../../../qualification/runtime-supervisor/LOCAL_EXECUTION_OBSERVATION_20261001_R4.json),
with candidate scope and remaining gates in the
[R4 audit](../../../qualification/runtime-supervisor/ADVERSARIAL_AUDIT_20261001_R4.md).
They apply only to their bound source and selected commands, not to a later
candidate, an unfiltered suite or target-host acceptance.

## Acquisition and final use

Both Agentd and Matrix adoption acquire an operating-system lifetime reference
before the existing bounded identity handshake. After a successful handshake,
the acquired reference is checked for exit before it is installed. A process
that exited during proof is missing; a failed identity proof still rejects and
never signals the occupant of the lease PID.

The adopted variant of `UnixProcessHandle` no longer stores a signalable numeric
PID. It retains only `ProcessRef`; `request_stop`, `kill`, and terminal polling
use that reference. There is no fallback from reference acquisition failure to
`kill(pid, signal)` or from exit observation failure to `kill(pid, 0)`.

Before sending an Agentd health or Drain frame, or a Matrix health frame, the
Unix connection must also prove the acquired process's peer PID through Linux
`SO_PEERCRED` or macOS `LOCAL_PEERPID`. `unix_peer_identity.rs` performs this check;
`unix_peer_identity_tests.rs` covers genuine and forged peers. This kernel check
supplements the lifetime reference and nonce/generation/root handshake. The
current Agentd/Matrixd contract requires the owned process to serve its listener;
transferring the listener to another process is not supported.

### Linux

`pidfd_open` acquires the stable task reference. `pidfd_send_signal` delivers the
fixed SIGTERM/SIGKILL controls through it. A zero-timeout `poll` observes task
termination through POLLIN/POLLHUP. Unsupported syscalls, descriptor exhaustion,
permission failures and invalid poll descriptors remain errors, not success or
permission to use an unbound PID. The kernel sets close-on-exec on a pidfd.

### macOS

A task-name right supplies the kernel audit token and is deallocated after use.
An EVFILT_PROC/NOTE_EXIT registration observes the original lifetime. The audit
token is re-read after registration so PID substitution during acquisition is
rejected. The one-shot terminal event is retained as an immutable observation.

SIGTERM/SIGKILL use the operating system's `proc_signal_with_audittoken` entry
point. Its kernel implementation revalidates pidversion and obtains the matching
process reference before signaling. The function is resolved from the fixed
system libproc path; unsupported systems fail explicitly rather than silently
using a numeric PID. Both library availability and host permissions are
qualification prerequisites. The original lifetime repair checkpoint recorded
no macOS execution in its editing environment; named macOS target-host
qualification remains a separate gate from later repository observations.

Native implementation references are Apple's XNU `bsd/kern/proc_info.c`
(`psignal_by_audit_token`) and `tests/signal_exit_reason.c`, plus Linux
`pidfd_open(2)` and `pidfd_send_signal(2)`. No Apple implementation source is
copied into this module; the Rust FFI uses those documented source interfaces.

## Exit status and child ownership

An adopted process is not assumed to be a child of this daemon. A kernel exit
observation does not supply a successful user-task result or an authoritative
exit code. The existing ProcessExit representation therefore retains
`success=false, code=None`; it does not reap an arbitrary current PID.

Freshly spawned Child handles remain exclusively owned. Before numeric signaling
that branch checks the owned Child's cached/wait status and refuses a signal
once it has been reaped. The product must not introduce a competing waitpid(-1)
reaper. Failed lease-publication containment is implemented separately in
`PROCESS_OWNERSHIP.md`; daemon death before a recoverable launch record remains
a separate ownership gap.

## Regression source and evidence boundary

`unix::process_ref::tests` adds five actual-process Rust tests for invalid PIDs,
exact lifetime signaling and exit, post-reap stale-reference rejection with a
later unrelated child, unsupported signals, and dropping a reference without
terminating a process. The stale-reference test does not force reuse of the same
numeric PID and must not be labeled a forced-PID-reuse host receipt.

Run the normal package qualification and the focused slice:

```sh
cd codex-rs
just test --locked -p codex-hepta-supervisor --lib unix::process_ref::tests
```

The original lifetime repair's editing environment ran a separate six-check
Python probe of the Linux pidfd kernel primitives. That probe was not execution
of these Rust sources,
Agentd/Matrix product qualification, macOS evidence, a daemon-crash experiment,
or an exact-candidate CI receipt. Subsequent compilation, formatting, strict lint
and selected native-profile outcomes are recorded in the observations above;
they do not establish every final-source or merge gate. No workflow policy or
required-check list is weakened by this change.

## Remaining program gates

Launch publication containment, same-owner cleanup, main-before-Matrix emergency
termination and durable operator Stop/Kill intent are current source mechanisms;
their qualification must follow the bound candidate. Remaining work includes
daemon-death launch/cleanup witnesses, complete release/control supersession and
predecessor/replacement crash coverage, restart-internal cross-daemon deadlines,
directory identity, source-map synchronization and target-host faults. This
amendment does not mark stages A-D complete or assert independent
security/operator acceptance.

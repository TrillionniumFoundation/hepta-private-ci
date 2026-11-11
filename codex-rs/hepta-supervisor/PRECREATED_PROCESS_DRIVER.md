# Original Supervisor handoff to a precreated process

`PrecreatedProcessDriver` connects the original `Supervisor::start` path to
children that already exist in their final image. The original Registry first
commits `Starting`, then constructs `SpawnSpec`; the driver sends that exact
value to the selected child. The original Supervisor writes its process lease
and owns subsequent lifecycle transitions. The driver never writes a Registry
generation, opens a writer or creates an authority grant.

The native G2 Root entry must select Manager and Recovery from its verified
kernel discovery page, retain their actual pidfds before accepting their
connections, and verify the required native credentials through its original
Root factory. The driver itself is a Linux process mechanism; successful host
tests do not prove kernel sealing, HOS2 capability binding or a G2 guest run.

## Binding and handoff

1. Root accepts a connection from each already-pinned child and calls
   `PrecreatedChild::from_stream` with the original expected peer and command.
   The original protected channel verifies `SO_PEERCRED`, pidfd type, actual
   PID and liveness. The driver also reads actual parent/start identity and
   checks `/proc/PID/exe` and bounded `/proc/PID/cmdline` against the command.
2. Root constructs one driver for its actual agent and one or two distinct
   children. Native role assignment remains a caller/kernel responsibility.
3. The child calls `receive_precreated_spawn` with its independently pinned
   actual parent. It remains in the same image and waits on the authenticated
   channel. No environment-supplied generation or second exec is involved.
4. `Supervisor::start` provides the exact original `SpawnSpec`. One request,
   at most 64 KiB, is acknowledged by the same pinned child with the SHA-256
   of its complete bytes. The complete handoff is bounded by 200 ms; the
   standby channel has the original 300-second lifetime bound.
5. Health and drain use the existing Agentd protocol through the original
   `UnixManagedProcess`. Handoff acknowledgement is not a healthy receipt.

Every attempted delivery consumes that child's slot before I/O. A missing,
malformed or uncertain reply never reconnects, resends or reuses the child with
another generation. Failure requests SIGKILL through that exact pidfd. Since
no successful process lease is returned on this path, the original parent must
finish reaping its already-held failed child before admitting a successor.
The driver does not wait indefinitely or claim that a kill request is a reap.

After successful handoff, stop/kill use `pidfd_send_signal`; `poll` uses
`waitid(P_PIDFD, WEXITED | WNOHANG)` and caches the actual terminal status.
There is no signal or wait fallback to a reused numeric PID. Ordinary
`UnixProcessDriver` children retain their existing behavior. Adoption from an
old serialized process lease is refused; that lease is not a new held child.

## Validation boundary

`precreated_tests.rs` starts real Linux children and uses the original
`FleetRegistry::initialize/register` and `Supervisor::start`. It checks the
actual received full `SpawnSpec` against the committed Starting generation,
absence of invented health, actual pidfd kill/reap, original lease cleanup,
one-use exhaustion, and rejection of a foreign pidfd or changed command.
The protected channel's own client tests cover complete request/response,
invalid input without a prefix, and permanent closure after lost, oversized,
truncated or timed-out replies.

```sh
cd codex-rs
just test -p codex-hepta-contracts --lib authority_host_issuer_transport::peer
just test -p codex-hepta-supervisor --lib precreated
just fmt
```

This is the lifecycle seam for the finite G2 entry. The original Root
initialization, protected Current/issuer, durable writer and synchronous HOS2
FinalUse composition must still be attached and measured in the complete
original ELF. Neither these host tests nor the handoff digest replace that
native effect/recovery evidence.

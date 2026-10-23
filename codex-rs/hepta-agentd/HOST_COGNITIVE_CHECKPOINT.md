# Protected original CognitiveStore checkpoint

`HostCognitiveCheckpoint` publishes the original `CognitiveCheckpointHead`
through the original root-only `HostAuthorityFrontierStore`. It adds no
Objective, operation, grant, nonce, effect or SQLite ledger. The fixed trusted
registration binds the original agent, publisher epoch, original writer lease
fields and retained peer lifetime. The surrounding service must enforce the
actual peer/pidfd, original live AuthorityLease dispatch boundary and original
frame/deadline policy. Constructing the registration is not authorization.

The runtime accepts only the five original closed32KiB request records:

| Command | Required state | Durable result |
| --- | --- | --- |
| read_head | Any existing state | Read actual durable head; never write request highwater |
| begin_writes | Current | Dirty |
| prepare_publication | Dirty and exact registered writer/owner | Publishing with complete proposal |
| commit_publication | Publishing | Current with the exact previously prepared cut |
| fence_publisher | Current, Dirty or Publishing | Fenced; retain forensic state without fallback |

Mutations compare the complete original protected head, advance the counter
with checked arithmetic, and retain the exact original request-byte SHA256 and
predecessor token. The32-character lowercase request ID encodes the fixed
publisher epoch and a nonzero sequence. Sequence gaps from read requests are
valid. Only mutations advance persistent highwater; stale mutation IDs are
refused. An exact replay of the last mutation returns its durable result without
another write; changing even JSON whitespace under that ID is refused.

ACK requires original durable CAS, its exact readback of the complete expected
result under the same original publication lock, and a post-I/O clock check
before the original writer expiry. The concrete original store performs that
file/directory sync and readback before returning success; the handler does not
open a second public-load window after a successful mutation. Before this
request has mutated anything, a busy original publication lock is a definite
Conflict refusal. After a CAS/storage uncertainty, the result remains Unknown.
The server token is a domain-separated hash of the complete typed head; clients
treat it as opaque. IO uncertainty, post-I/O expiry or an unexpected readback
returns Unknown without a head/token and permanently closes this backend object.
The original transport must still refuse a late/dead-peer response before its
first prefix byte. Neither cancellation nor an Unknown response proves a CAS
did not commit. The original whole-pool client gate must permanently fence.

`initialize_fresh` is a trusted root bootstrap API, absent from the wire. The
launcher must allocate a genuinely new, exclusive empty directory, call the
original `CognitiveStore::open`, capture `recovery_anchor`, and await `close`
before registering that exact cut. An existing/partial protected head is never
overwritten. Runtime `open` cannot create a missing head, change registration,
promote Dirty/Publishing/Fenced to Current, or hash an existing suspect database
to invent recovery evidence. This module provides no remote re-registration endpoint.

The trusted `adopt_current` API adds a narrow same-boot clean restart stage.
Root must have captured and retained the old publisher's actual pidfd while its
exact boot/PID/start-time/UID identity was alive. A PID recorded after exit or a
deserialized identity cannot replace that object. The old pidfd must now report
exit and a separately captured exact successor must still be alive. The
launcher must hold the new writer's original live registry dispatch fence, with
the old writer retired through the original lease lifecycle. This backend API
does not grant or rotate that authorization.

Adoption compares the complete existing Current head and its original token,
keeps its exact retained cut, increments the original counter and publisher
epoch, and starts a fresh request highwater only within that new epoch. The
same local lease ID must advance generation by exactly one and the original lexicographic
authority/owner epoch, with a different full grant and fencing digest. Original
CAS sync/readback and a final clock/process check precede success. A lost result
may have committed: reconcile by opening that exact new registration. Never
choose another identity or initialize fresh after an uncertain result.

This stage refuses actual Dirty, Publishing and Fenced heads. It cannot recover
after losing the retained old pidfd (including a Root process restart), adopt
across a reboot, validate suspect SQLite bytes, rotate the canonical issuer's
retained writer proof, or restore unfinished effects. Those require separate
trusted composition and recovery evidence; a clean handoff does not close them.

The explicit root/data tests create fresh original SQLite databases, use their
real coherent anchors, and exercise actual root-protected CAS/reopen, exact
replay and changed-byte refusal, read highwater, binding/epoch rejection,
post-CAS expiry and a two-handle race. Their clock and authority-binding values
are controlled qualification inputs, not production grants. Those tests do not
by themselves qualify the service wire, real live authorization, physical power
loss or a production writer/effect/recovery loop. The service remains unavailable
until its trusted bootstrap and original live-lease handler actually attach this
backend and pass their separate integration tests.

Recorded local qualification (2026-10-23): source `3f023c18717a578d1beb9027eb61919b5f2ba4be`
passed all seven explicit root/data tests through the original `just test`
entry, 5.443s, 273 other tests skipped by the explicit filter. This includes
actual file disappearance/restoration without reviving the uncertain object,
post-CAS expiry, exact replay/reopen and the two-handle publication race. All
tracked inputs were byte-identical before/after. The earlier `792626129` run
is retained as five passed/one failed: its new race fixture incorrectly required
only Conflict, overlooking original nonblocking-lock refusal and a winning
higher request sequence. Source `c36023c964` then passed seven tests; the final
semantic phase removed the redundant post-CAS public load and passed seven
again. Original clock/transport deadlines were not changed. Raw evidence lives
in `/data/asterinas-audit-build.8tdrjboi/root-checkpoint-qualification-01`, `-02`
and `-03`; formatting/lint follows these test phases without another same-phase
test run. [Published original receipts and logs](acceptance/2026-10-23-root-authority/README.md)
include the earlier failures and successful finish. This does not qualify the
real service/bootstrap/live lease.

The trusted initial Current publication uses global counter 1 while its publisher
mutation sequence remains 0. This matches the original client's positive-counter
contract; no fictitious Begin/Prepare/Commit requests are issued. Runtime open
rejects zero-counter records instead of silently upgrading a retained head.
A trusted clean adoption advances the global counter once and resets only the
new publisher's local sequence. A CAS conflict remains a definite pre-write
refusal. All storage errors other than that conflict, and every clock/pidfd
failure after a successful CAS, return Unavailable: the exact new head may
already be durable and must be reconciled instead of reissued.

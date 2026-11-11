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

This stage refuses actual Dirty, Publishing and Fenced heads. It cannot adopt
across a reboot, validate suspect SQLite bytes, rotate the canonical issuer's
retained writer proof, or restore unfinished effects. Those require separate
trusted composition and recovery evidence; a clean handoff does not close them.

If Root lost its retained predecessor pidfd, the separate non-deserializable
`RetiredCheckpointPublisher::observe` can establish same-boot retirement from
the actual kernel: pidfd_open must report ESRCH, its actual new pidfd must report
exit, or a live pidfd bound to the same PID must expose a different process
start-time. A UID change alone never proves exit; an unreadable /proc record,
unavailable pidfd primitive, identical start-time or different boot refuses.
The launcher runs in the original pinned PID space. No peer exit flag is trusted.

`adopt_current_after_root_restart` uses exactly the original clean adoption CAS,
including exact protected predecessor lifetime, complete receipt/token, local
lease one-step succession, captured live successor, original durable cut and
post-CAS uncertainty. This observation creates no new authority and never
bypasses the original local lease expiry/legal release. Its component tests
drop every original old pidfd and service object before obtaining the separate
kernel proof; this does not itself qualify an actual Root process restart,
cross-store issuer reconciliation or an end-to-end recovered writer.

[The nineteen-test retirement qualification](acceptance/2026-10-23-retired-publisher/README.md)
records the actual kernel/CAS cases, frozen source, original scoped fix and
explicit committed-range formatting. It preserves the fixed-PID-namespace
precondition and does not claim actual whole-service restart or Dirty recovery.

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

The separate frozen `338bf7ed` phase passed all 14 explicit Root tests, including
the real pidfd handoff/uncertainty cases and a fresh head bound through the
original CognitiveStore client. Its earlier `44ed8335` phase failed two of 14;
those failures and the unchanged-input, empty-diff finish evidence are retained
in [the complete adoption receipts](acceptance/2026-10-23-checkpoint-adoption/README.md).
This is the clean same-boot backend boundary; real service/issuer and cold or
Dirty recovery remain separate requirements.

The service can now explicitly open `checkpoint_state_dir`, an existing private
child of its configured protected state. The root registration supplies the
publisher epoch and actual UID/PID/boot/start lifetime. The service derives the
complete original writer binding through `VerifiedRootWriterProof` and its
`ProductionAuthorityLease`, including the original grant and grant-bound token
digest methods. Neither the wire nor a JSON recovery cut supplies this binding.
Missing state, a different writer/token/publisher or a different peer lifetime
refuses opening; there is no automatic initialization or publisher adoption.

Every checkpoint request holds the original exact writer lease dispatch fence
through retained-proof validation, the original backend exchange and the final
issuer-head/clock/expiry check. The original 32KiB closed DTO and peer pidfd/frame
deadlines remain. A live-lease failure emits no response prefix and the client
must remain fenced. The existing backend's uncertain-publication semantics still
apply. No remote genesis, renewal, cut rehash or previous-Current fallback is added.

The no-effect service fixture prepares its genuinely fresh original CognitiveStore
and captures its coherent anchor before starting the protected clock or leases.
It checks Current reading, Dirty and terminal Fenced publication, exact duplicate
ACK and stale CAS refusal. It deliberately does not manufacture an original
writer's `lease_sha256` for a Prepare/Commit claim. Complete production-writer
publication and restart reconciliation require the actual owner integration.

The first service integration phase compiled with Rust 1.96 and passed 41 scoped
tests. Its actual root/data-bind run refused initialization with `Unavailable`
before entering the dedicated UID 60001 channel. A separate diagnostic trace
reached the channel (141ms observation) but then refused another operation with
`Unavailable`; it is diagnostic evidence, not a successful service run. The
original one-second clock horizon and 500ms feed freshness remain unchanged.
That frozen phase's fresh-head counter also predates the separately identified original
client counter-zero incompatibility. This phase does not qualify fresh whole-writer
binding, complete publication or persistent-service availability.

The separate root/data-bind expired-writer negative did pass: the actual dedicated
UID 60001 waited three seconds after a two-second original writer authorization,
received no checkpoint response prefix, and left the original protected Current
head unchanged. This proves the expiry refusal only, not the positive service path.

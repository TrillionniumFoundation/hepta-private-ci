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
to invent recovery evidence. A later publisher requires explicit trusted
reconciliation; this module provides no remote re-registration endpoint.

The explicit root/data tests create fresh original SQLite databases, use their
real coherent anchors, and exercise actual root-protected CAS/reopen, exact
replay and changed-byte refusal, read highwater, binding/epoch rejection,
post-CAS expiry and a two-handle race. Their clock and authority-binding values
are controlled qualification inputs, not production grants. Those tests do not
by themselves qualify the service wire, real live authorization, physical power
loss or a production writer/effect/recovery loop. The service remains unavailable
until its trusted bootstrap and original live-lease handler actually attach this
backend and pass their separate integration tests.

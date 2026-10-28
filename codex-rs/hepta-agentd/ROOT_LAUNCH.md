# Original Root trusted launcher API

`initialize_host_authority_owners` is a Root administrator operation, separate
from opening the runtime service. It reads existing private service and peer
registration files, verifies the actual peer lifetime and original writer
proof, then initializes three new private namespaces through the original
checkpoint and consumer implementations. The supplied cut must have been
coherently captured by the genuinely fresh original CognitiveStore owner before
that store is released. This API accepts no database path, computes no local
replacement cut and never overwrites an existing or partial namespace. A failed
initialization retains partial state for investigation.

`capture_host_authority_bootstrap` opens existing state only. It verifies the
actual registered peer, public issuer pin, original live writer lease, exact
Current writer/peer/publisher binding and original consumer frontiers. It checks
the separately provisioned UID-owned local consumer directories for canonical
paths, ownership, mode and device/inode aliasing. It returns only the existing
public bootstrap. Original protected clock renewal may perform its existing
durable clock CAS; this does not create or repair checkpoint/consumer state.

The existing Root executable exposes `capture-and-serve --config PATH
--registration PATH --device-local PATH --notes-local PATH
--owner-pidfd-stdin`. It flushes public handoff JSON to stdout, then serves the
five lanes in that same process. A one-shot capture command followed by a new
service process would bind the handoff to the wrong Root lifetime and is not
provided. The trusted launcher must retain the actual Root pidfd and pass its
pre-held consumer pidfd, publish the public bundle through its controlled
handoff and connect the five lanes. Ordinary peers cannot call this API over
those lanes or select paths through service requests.

Both operations require the explicit existing Root bind and private Root
configuration. There are no defaults for signer, lease, revocations, clock,
writer, frontier or Current. Opening a missing service still fails closed.
The fresh namespace API is deliberately not exposed as a command accepting an
arbitrary user-supplied digest. A production deployment must establish the
provenance of its genuinely fresh genesis or independently retained Current.

The isolated Root service qualification consumes these same APIs. It creates
private consumer directories before releasing its UID 60001 client and verifies
that a repeated fresh initialization is rejected. The client opens the original
FinalUse journals in those pre-created directories. This qualification does not
provision an existing deployment or change its policies.

Development validation uses the owning Agentd library through `just test`, the
explicit isolated Root/SQLite qualification, scoped `just fix -p
codex-hepta-agentd`, then `just fmt`. Keep negative attempts and exact executable
fingerprints with the resulting qualification evidence.

# Root observation and original writer client

`AgentdRootAuthoritySession` is the Linux client for the original root service's
closed observation v2 and retained writer authorization v1 protocols. It does
not create an issuer, registration, signing key, local writer ledger or recovery
genesis. The `authority_host_wire` types and their signing bytes are shared with
the server.

## Bootstrap and original owners

The trusted launcher passes one connected Observation stream, an already held
root pidfd, exact PID/boot ID/process-start identity, and
`AgentdRootWriterTrust`. The latter contains the canonical issuer public key and
ID, registered AgentId/spawn, owner epoch, local lease ID/generation, and the
complete original `AuthorityLease` from root registration. No field comes from
renderer input. `connect` requires UID 0 and reads the retained proof on that
same stream, then switches to observation v2. There is no reconnect operation.

The client strictly verifies the domain-separated Ed25519 signature, original
lease shape/hash and all registration fields. The original
`ProductionAuthorityLease` uses the SHA-256 of the complete canonical signed
proof, its verified lowercase signature ASCII as the opaque token, and the
original expiry rounded down to Unix seconds. `from_verified_parts` performs
only shape validation; the retained verifier supplies actual current evidence.

The installation sequence is:

1. Await `AgentdRootAuthoritySession::connect` with a request timeout at most
   500 ms and stream lifetime at most 300 seconds. Retain this session handle.
2. Use `clock()` and `revocations()` while independently opening the original
   Device and Notes `FinalUseAuthority` owners. Each owner keeps its own original
   state directory and fixed external frontier client; the canonical issuer key
   may be shared. The read feed already runs during bootstrap.
3. Await `activate_final_use_owners` with clones of those exact original owners.
   It synchronizes and reads back their heads before enabling the verifier.
4. Supply `authority()` and `verifier()` to the single original protected writer
   factory, along with its independently retained Current checkpoint receipt.
   Pass the same FinalUse instances to the Device runtime and Notes attachment.
   The original sender, operation writer, and Notes host retain their ownership.

The root client does not replace the protected checkpoint binding or validate a
root deployment merely because a constructor returned. Missing registration,
current cut, physical device attachment or Notes storage readiness remains a
separate bootstrap failure.

## Currentness and revocation barrier

Pure verification performs full original authority equality, a zero-wait check
of the retained root pidfd, and a memory/BOOTTIME cache read. It performs no
network, filesystem or durable-owner callback. Clock projection rounds elapsed
nanoseconds up, stays within the root's durable ceiling, and counts suspend.
The 500 ms freshness window begins before the observation request. A stale
window, rollback, identity/proof mismatch or uncertain exchange permanently
fences the session; a late response cannot restore it.

Global registry revision may rise because unrelated leases changed. It may not
regress, and it cannot substitute a different fixed lease or proof. Revocation
revision cannot regress; an unchanged revision requires the entire same head,
and increasing revisions cannot remove revoked IDs.

When the head changes, the feed pauses public currentness, validates the full
observation, and updates each installed original FinalUse owner through its
original persistence/frontier API. Only after every exact head reads back does
it publish currentness. Failure or exceeding the same freshness deadline fences
the session. Delayed blocking persistence cannot publish a later success or
start another update after fencing. An unchanged-head refresh does not touch
consumer storage. Local brief read contention returns unavailable without
waiting; it does not invent fresh evidence.

Dropping the session or losing its background task also fences previously
returned clock and verifier clones. Original read-only recovery data remains
owned by the original stores; this client does not replay any effect.

## Qualification boundary

Tests use explicitly synthetic Ed25519 keys and a private same-UID constructor
for socket fixtures. They exercise canonical signature/hash conversion, closed
wire decoding, original socket framing/cancellation, BOOTTIME mathematics,
revision and identity binding, and two real original FinalUse stores with
separate fixture frontiers. Blocking and failed consumer updates must refuse
pure verification. These are client qualifications, not proof that a root
service, its protected directories or a complete device/Notes deployment was
installed and qualified.

## Public trusted-launcher bundle

`HostAuthorityPublicBootstrapV1` in `authority_host_bootstrap.rs` is the shared
closed JSON shape (`schema_version: 1`, `operation:
"runtime.authority.bootstrap.v1"`, at most 64KiB). It contains the original
root/consumer lifetime records, registered identity, public issuer key,
revocations, exact writer registration and signed proof, complete protected
checkpoint head, two original consumer frontiers/local journal paths, and the
five mandatory socket paths. `checkpoint.last_current` is the original complete
local cut. Both consumer owner IDs are the canonical signer ID; their protected
root directories and original local journals remain separate.

`HostAuthorityPublicIssuerKeyV1` serializes only the original public trust-key
fields and converts to/from `FinalUseIssuerTrustKey` without defaults. The key,
PID, proof and cut are not authenticated by JSON decoding. The trusted launcher
must separately transfer its already held actual root/consumer pidfds and the
fixed bootstrap descriptor; the compiler must validate that root source and all
purpose/identity/binding fields before constructing the original clients. No
private signing key, protected root directory FD, clock fallback, genesis claim
or successful production-authority receipt is part of this bundle. Actual
deployment qualification and example bundles come from the live root launcher,
not a fabricated cut or a user-filled recovery template.

The [original wire/proof type qualification](acceptance/2026-10-23-public-bootstrap/README.md)
binds the six-test Rust1.96 scope and finish. It does not certify a live bundle,
receiver loader or five-lane deployment.

## Trusted writer succession

`DeploymentFinalUseIssuer::rotate_writer_authorization` is a trusted launcher
API, absent from peer wire. It uses the verifier retained by the canonical
protected factory, the original registry's retired-predecessor/live-successor
fence, and the same issuer key, durable head and shared sequence. It strictly
authenticates the complete old retained proof without requiring that old lease
to remain temporally live. Exact original revocation, expiry or original pruning
is required; a missing or arbitrary replacement lease is not retirement.

The trusted launcher must separately prove old publisher quiescence with its
retained pidfd, capture the exact new registered identity/peer, and supply that
full successor registration. Local writer generation advances exactly once;
actual Fleet spawn must increase and may skip failed starts. No peer may choose
these values. The registry callback never reenters the registry owner.

Only an exact already retained successor may reconcile a lost ACK without a new
sequence. An error may follow a durable sequence reservation or replacement and
does not permit rollback or another invented generation. Checkpoint adoption is
a separate protected CAS: a crash between the two stores must refuse runtime
opening until exact trusted reconciliation. This API does not recover Dirty or
Publishing, initialize a missing cut, renew a live predecessor, or add another
issuer/nonce ledger. Original-owner unit tests are not deployment qualification.

Source `035d67e9` passed the original 46-test owner/service/wire/proof/sender
scope on Rust1.96, followed by scoped fix and fmt. The five new rotation cases,
two retained compile/lint failures, complete logs and source digests are linked
from [the rotation qualification record](acceptance/2026-10-23-writer-rotation/README.md).

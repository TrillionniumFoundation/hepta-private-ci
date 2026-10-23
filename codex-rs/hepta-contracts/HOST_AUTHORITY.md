# Local host authority backends

`RootAuthorityDirectory` and `HostAuthorityFrontierStore<F>` implement the
existing `AuthorityFrontierStore` contract for a root-owned host broker. They
do not create an authorization policy, signing key, writer, or business outbox.
The original FinalUse and authority-lease owners remain responsible for
signature, epoch, revocation, nonce and effect-entry decisions.

## Protection boundary

The broker's directory must be outside the Agent's writable state. Opening it
requires effective UID 0, an absolute path, root-owned ancestors without group
or other write permission, and a mode-0700 final directory. Each component is
opened relative to a retained descriptor without following symlinks. The
backend retains the directory descriptor.

This protects a frontier from an unprivileged writer restoring or deleting its
own local authority directory. It assumes a trusted operating system and root
administrator. It does **not** claim TPM protection, remote attestation, or
resistance to rollback of the whole host and its protected directory.

Agent processes must not directly receive this directory handle. A separately
authenticated private broker channel supplies their `AuthorityFrontierStore`
callback. The backend alone does not establish that channel or peer identity.

## Persistence and failures

Each authority owner has one bounded JSON frontier record, addressed by a
SHA-256 hash of its owner ID. Records are limited to 16 KiB. Mode-0600 regular
files must have exactly one link and the broker's UID. Registration is explicit
and only succeeds when the owner has no existing record. Opening never creates
or repairs state. Different original owner domains need different owner IDs.

CAS takes a nonblocking process lock, reads and compares the complete expected
value, writes and fsyncs a private temporary file, atomically renames it, then
fsyncs the retained directory, then compares the exact readback under the same
lock before acknowledgement. Those file/directory syncs have already completed;
the readback does not repeat them. Public load/open also acquire this
publication lock and sync both the observed file and retained directory. They
cannot report a renamed value while another publication still owes its directory
sync. Lock contention, failed sync or failed readback remains unavailable/uncertain;
visibility alone is never a durable acknowledgement. The internal CAS predecessor
read uses its already-held lock and does not recursively acquire it.
Lock identity is rechecked after acquisition.
A stale incomplete temporary file can be replaced under that lock; an unsafe
file or symlink is refused before truncation. A killed process releases the OS
lock. Uncertain errors remain errors; callers must use the original owner's
fencing/reopen protocol, rather than assume that a failed call did not commit.

FinalUse already advances its external frontier before appending its local
nonce journal. If the latter fails, an ahead-of-local external frontier rejects
reopen. The host must retain that mismatch for authorized recovery; it must not
reset the protected frontier from the local directory.

## Verification

`authority_host_store_tests.rs` exercises actual filesystem CAS/reopen, two
concurrent processes with one winner, controlled SIGKILL after durable commit,
stale temporary files, unsafe entries, and original FinalUse signature/nonce/
revocation checks followed by rejection of a restored local snapshot.
The tests' ordinary-UID directory helper is private to their test module. It
does not relax the production root-directory constructor. Subprocess entry
tests are marked ignored and are launched explicitly by their parent cases.

## Linux protected clock

`HostAuthorityClock` stores a separate, explicitly registered clock frontier.
It samples the running kernel's boot ID, CLOCK_BOOTTIME and CLOCK_REALTIME.
BOOTTIME includes suspended time. The retained actual-time anchor and a fixed
1000 ms future observation ceiling are separate values. CAS/fsync commits that
window; a new actual BOOTTIME/REALTIME sample is then taken after I/O. Only a
post-I/O reading inside the already durable window can be returned. Slow I/O,
a boot change during I/O, samples spanning over 10 ms, invalid arithmetic or
backwards clocks fail closed. A future ceiling is never returned as actual now.

Within the same boot, sampled wall time has its own retained highwater, separate
from the monotonic BOOTTIME mapping and future ceiling. Wall samples anchor to
the earlier BOOTTIME reading to form a conservative upper projection. The
post-I/O value uses this already durable mapping at the later BOOTTIME reading.
If a post-I/O wall step is ahead of that mapping, the observation is refused;
it needs a new mapping committed first. No unretained forward value is published.
The integer-ms public anchor preserves its exact sub-ms BOOTTIME phase, so its
projection equals the returned observation and a refresh cannot round backwards.
After reboot, realtime must conservatively reach
the previous ceiling, which bounds every formerly published value. Opening
never resets it. Earlier clock records without a ceiling are refused, not
silently migrated or replaced. This cannot detect a whole-host snapshot that
restores both the protected frontier and OS time. Root and the OS remain trusted.

`refresh_projection` exposes a public boot ID/BOOTTIME anchor, anchor Unix ms and
durable ceiling, plus an actual post-I/O observation. A cached reader must match
the kernel boot identity, advance time with actual BOOTTIME and reject values
beyond the ceiling. This API does not supply an authority epoch, revocation head
or authenticated/fresh delivery channel; the original host must bind those.

Clock tests cover actual Linux sampling and reopen, a retained future watermark
that refuses to reopen without rewriting state, and projection/reboot/rollback
boundaries. Explicit root-only cases delay acknowledgement of an actual
filesystem CAS/fsync/rename/dirsync, then check both window expiry and original
FinalUse token entry after grant expiry. The same two cases fail with the old
pre-I/O-return behavior. Their root-owned `/run` fixture tests the clock and
entry boundary; it does not qualify persistence across power loss.

## Local key custody and issuance

`HostFinalUseIssuer` explicitly creates a fresh OS-random Ed25519 key in this
root directory. Opening an absent, unsafe or different identity fails; it never
regenerates keys. Only the public trust key leaves the issuer API. Grant issuance
requires a live existing `AuthorityLeaseRegistry` lease with exact subject,
operation class, destination, scope and payload, revalidated under the original
lease dispatch fence. Grants expire within thirty seconds and no later than the
lease. This API does not create leases or CognitiveStore recovery cuts.

The issuer has no second FinalUse journal. The consumer retains the original
FinalUse signature/nonce/revocation/effect-entry owner. Lease revocation stops
new issuance. Already signed grants additionally require the original FinalUse
revocation protocol or expiry; lease revocation alone is not a claim of their
instant invalidation. Tests use new real keys and original FinalUse/lease owners
to verify signatures, replay denial, changed binding denial and both revocation
paths without entering an effect.
Ordinary issuer/transport timing fixtures use actual Linux clocks and fsync on
tmpfs. They isolate deadlines and bindings from unrelated disk contention;
they do not qualify power-loss persistence. Store CAS/crash tests use their
selected filesystem, and the explicit root peer case accepts a separately
selected protected state parent while retaining the production path checks.

## Private Linux issuer channel

`HostIssuerSession` accepts an already connected Unix stream and a root-launcher
policy that pins the actual UID/PID and an existing lease ID/revision. Linux
SO_PEERCRED must match before any request is read. The original Agentd's u32-BE
JSON request/response format is preserved, with a 16 KiB request and 64 KiB
response bound. Only a full denial keeps the channel reusable. Invalid frames,
uncertain exchanges and elapsed deadlines permanently close it. There is one
exchange at a time and no discovery, reconnect, retry or administrative lease
endpoint. The launcher must control descriptor inheritance/transfer and retain
the peer lifecycle; matching a stale numeric PID alone is insufficient.

The trusted launcher supplies an already-held Linux pidfd for this exact owner,
before accepting the connection. Its descriptor type and process identity must
match; opening a numeric PID again from an inherited connection is insufficient.
Nonblocking stream I/O polls the socket and retained pidfd together. Owner exit
wins over readable socket data, including when a descendant keeps the old stream
open. Waiting for the first byte is idle time; the thirty-second request deadline
starts with that byte and applies to the remaining frame, issuance and response.
A separately configured hard session lifetime is at most 300 seconds and cannot
be refreshed by requests. Expiry closes this capability. It does not issue a new
publisher generation, reconnect or reopen a writer gate. A runtime loader must
renew its private channel only at an independently authorized quiescent boundary;
that production renewal/recovery integration is not supplied by this transport.

Socket I/O uses one deadline capped at thirty seconds. This does not cancel
kernel filesystem I/O inside the issuer. After such an operation returns, an
expired deadline cannot emit a successful grant. A root-only test launches a
real nonprivileged UID with empty supplementary groups and NoNewPrivileges,
checks SO_PEERCRED, denies root-directory access and verifies the resulting
grant with original FinalUse. A login administrator with sudo is not a confined
writer; deployment needs a dedicated non-login UID without sudo permission.

The runtime loader, authenticated clock/head feed and cognitive current-cut
protocol remain separate requirements. These tests do not attach a production
CognitiveStore writer or establish full crash recovery.

## Canonical root service integration

The Agentd host service selects the original `DeploymentFinalUseIssuer`, with
one retained Ed25519 key, revocation head and durable sequence shared by original
FinalUse issuance and canonical AuthBus Objective signing. `HostFinalUseIssuer`
remains a library/qualification primitive; it is not a second deployed issuer.
The root factory preserves exact original lease revision/binding checks and
post-I/O expiry rejection. A discarded or undelivered signature never refunds
its retained sequence. Original FinalUse still owns nonce consumption.

`hepta-authority-host initialize --state STATE --bootstrap ROOT0600_JSON` is an
explicit fresh administrative authorization. Existing/partial state is refused,
not reset. It emits only the new public key/lease identity and
`production_ready=false`; it creates no CognitiveStore genesis or current cut.
`serve-session --config ROOT0600_JSON --registration ROOT0600_JSON
--owner-pidfd-stdin` opens that state without initialization. It requires the
configured actual bind mount and exact device/inode, public key pin, registered
original identity/current spawn, actual boot/start identity, dedicated UID,
empty supplementary groups and NoNewPrivileges. The trusted launcher retains
its child and supplies the already-held pidfd as stdin before any connection.
Configuration and registration are root-owned single-link 0600 files in a
protected 0700 directory. The original Agentd writer lock is never reacquired
by the authority service merely to reconstruct its registered identity.

Three separate purpose-limited private listeners use the same owner lifetime:
observation 16 KiB, issuer 64 KiB (original FinalUse requests remain 16 KiB), and
checkpoint 32 KiB. `HostAuthorityPeerChannel` is a server-only framing helper
using the existing pidfd/deadline implementation. It pre-encodes and bounds the
entire response before emitting a length prefix. The observation carries the
complete original head and post-I/O clock projection; it never truncates revoked
IDs. Capacity includes the existing 16 KiB protected record and observation
bounds, so 256 maximum-sized IDs are not a promised operational capacity. An
oversized record/observation fails closed. Administrative quiescence and an
original protocol epoch/key handoff are needed before resuming a full owner;
this CLI does not invent an automatic reset/rotation endpoint.

A client must start its 500 ms feed-freshness measurement before reading,
validate the root peer and registered identity, and permanently fence its writer
generation on expiry, failure or rollback. It projects actual matching-boot
BOOTTIME from the retained anchor and refuses beyond the durable ceiling; the
ceiling is never actual-now. Service threads keep the feed out of a signing work
queue, but do not turn a slow fsync into a fresh observation. The 300-second hard
session cap requires an independently reconciled quiescent loader handoff;
ordinary requests cannot renew it or restore a permanently fenced writer.

Explicit root qualification runs the original grant client and canonical
AuthBus signature verification from UID60001 against data-backed persistent
state with real fsync, SO_PEERCRED and retained pidfd. An absent checkpoint
registration closes its lane without any successful record. This qualifies the
service/factory boundary, not production loader, genesis, current-cut recovery,
whole-host antirollback, native-kernel compatibility or G2 control admission.

`cargo build -p codex-hepta-agentd --example
authority_host_peer_qualification --profile dev-small --locked` builds a thin
no-effect peer without the full libtest harness. The explicit root qualification
can select it with `HEPTA_HOST_AUTHORITY_QUALIFICATION_CLIENT_BIN`. Its public
`HEPTA_SERVICE_*` fixture inputs are supplied by that privileged launcher, not a
production bootstrap. It checks actual UID60001, cleared capabilities/groups,
NoNewPrivileges, root peer credentials on all three streams, state-directory
access denial, feed freshness measured before reading, and original signature
verification/shared sequence. Missing checkpoint state still produces no ACK.
It is a qualification executable and carries no native control role or writer
current-cut authority.

Every v1 observation now revalidates the configured original lease through its
original verifier and dispatch fence, including the exact cloned revision,
revocation, registered subject and epoch. The fence covers the local head read
and final clock projection. The response is refused if the lease expires during
that I/O; another clock-writing check after producing the projection is avoided.
The unchanged v1 wire still supplies no complete production writer proof or
consumer frontier adapter. A fresh two-second no-effect qualification lease,
observed after three seconds, must close the feed without a response prefix and
deny the original FinalUse request. Restoring the earlier head/clock-only handler
makes this actual dedicated-peer regression fail. All original bounds remain.

The canonical issuer also has an explicit trusted-root writer registration API.
It requires a separate original lease whose operation is
`runtime.agentd.production_writer`; a per-effect FinalUse lease is rejected.
The exact Agent, spawn, owner epoch, original local lease identity/generation
and complete registry lease are signed in the shared typed domain. The original
issuer counter is durably reserved before signing, and the complete proof is
retained in that same issuer state before return. Expiry during either durable
write refuses publication without refunding the sequence. Repeated exact
registration returns the retained proof; different registration cannot overwrite
it. This stage supplies no peer signing RPC, automatic renewal, genesis or cut.
The original registry's global revision remains observation metadata: unrelated
lease changes advance it without invalidating the exact registered writer lease.

The root0600 service configuration can optionally register `writer`, with the
exact `HostAuthorityWriterRegistration` fields. The explicit administrator command
`hepta-authority-host register-writer --config /protected/service.json` installs
that new original writer lease in the existing protected registry and retains the
proof using the same canonical issuer. An existing different lease or proof is
refused. `serve-session` only opens this registration; absent proof/lease or a
mismatched Agent/spawn refuses startup. It never invokes registration itself.

On the observation stream, `runtime.authority.writer_authorization.v1` returns
that exact retained proof; it does not sign or spend another sequence.
`runtime.authority.observation.v2` returns the shared V2 DTO, including the exact
original writer lease, its digest and original registry global revision. Both
operations hold the original writer lease dispatch fence through local reads and
the final post-I/O clock observation. They share the original 16KiB bound; an
oversized complete head is refused without truncation. V1 remains available.

At the first V2 stage, this service extension had not passed persistent-host availability qualification.
The initial two actual data-bind qualification attempts refused during the older
initialization path, before writer registration: the fixed one-second protected
clock horizon was exceeded by actual filesystem synchronization. Those failures
remain evidence, not successful writer or current-cut receipts. No horizon,
request deadline, feed freshness or production readiness claim was relaxed.

## Original consumer frontier client

`RootFinalUseFrontierClient` implements the original
`AuthorityFrontierStore<FinalUseFrontier>` on an exclusive, already-connected
purpose-limited root-service stream, one fixed stream for each original consumer. Trusted launcher inputs fix the local `owner_id`,
root PID/boot/start identity, pre-held root pidfd, timeout and lifetime. The public
constructor requires UID 0. It cannot connect, reopen a numeric PID, select a
remote owner/type, initialize/reset state or administer epochs. The original
consumer remains responsible for computing its complete canonical state hash;
this narrow root store does not infer state monotonicity from an opaque digest.

The shared `HostConsumerFrontier*V1` values live in contracts and remain
re-exported by Agentd. Each u32BE-framed request/response is at most 16 KiB.
Request IDs are nonzero, increasing and echoed exactly. CAS sends the complete
original expected/next frontier and accepts ACK only with exactly `next`. A
complete conflict can be returned without retry; all uncertain outcomes,
including lost ACK after remote commit, permanently discard the stream and
return `Unavailable`. The original authority must remain fenced in that case.
There is no reconnect or new-ID replay inside this client.

Device and Notes are separate original consumers. Each requires its own client
instance, fixed root endpoint, owner and protected backend; they must not share
a frontier. The owner is never transmitted as a request selector.

Calls perform synchronous bounded storage I/O at the original authority's
persistence boundary. They must not be installed as clock or live-verifier
callbacks. Concurrent misuse fails immediately rather than interleaving frames.
Tests use private same-UID socketpairs for protocol faults and verify public
root-identity rejection; these do not establish deployment qualification for a
root service or a consumer running under a separate UID. That qualification
requires the real launcher, registered original consumer and protected backend.

Protected frontier reads can reuse a durability witness for an immutable record
that this exact backend handle has already acknowledged. The witness retains the
open file descriptor and complete encoded bytes. Every read still takes the
original publication lock, reopens and validates the current private file, and
compares its device/inode plus every byte. This avoids repeated file/directory
sync only for that exact retained record. A new handle or replacement inode,
changed bytes (even at the same length), or any I/O failure requires actual
synchronization again. Failed publication never installs a witness. This is no
mtime/size/hash shortcut and supplies no new authority or rollback guarantee.
All protected clock post-I/O, rollback and one-second horizon guards remain.

The witness stage passed the original blocked-publication/durability tests plus
four new real-file cases: exact repeated read, a second handle's replacement
(including equal bytes with a new inode), same-inode same-length changed bytes,
and failed read followed by restoration. A controlled length-only comparison
made the changed-byte test incorrectly return a value and fail. On the real
root-owned data bind, subsequent dedicated-UID60001 qualification verified the
retained proof at sequence 1, original Objective/FinalUse sequences 2/3, and a
111ms V2 read-before-feed observation. The expired-writer and legacy V1 cases
also passed. The earlier initialization failures remain valid evidence of
host-I/O unavailability; this is no sustained latency SLA, current-cut witness,
full production writer or G2/native qualification.

The service's Objective signing path now holds the original registered writer
lease dispatch fence through the canonical signer. It requires the exact retained
writer proof and fixed Agent/spawn, checks the original live lease before spending
a sequence, caps Objective expiry at that lease's expiry, and discards a response
that expires during durable I/O without reusing its sequence. The generic canonical
signer retains its existing semantics for other callers. A service without a writer
registration refuses Objective signing; it can still exercise the original v1 feed
and per-effect FinalUse path. An effect lease is never substituted for a writer.

Four focused regressions cover the expiry cap and original claims, changed/revoked
leases, expiry after the durable sequence reservation, and wrong proof/spawn. The
real persistent-bind UID60001 qualification then passed five cases: proof plus
Objective/FinalUse sequences 1/2/3, expired Objective without a response prefix,
expired feed plus refused FinalUse, and the thin and library clients without a
writer. The positive V2 observation measured 68ms from before the read. The fixture
performs setup negative checks before registering its fresh lease and releases
the client through a readiness pipe only after root setup; the original connection,
I/O, clock and freshness deadlines are unchanged. The earlier ten-second fixture
lease that expired during setup is preserved as a failed attempt. These results
still supply no checkpoint ACK, current-cut recovery, native V2 qualification or
production readiness claim.


Original general-lease verification now samples the authority clock only after
acquiring the owner/revocation mutex. Time spent waiting for a preceding local
boundary cannot extend a lease into a later consumer or dispatch entry. Clocks
supplied to this original registry must be independent of that registry and must
not reenter it. `with_verified_use` still releases the owner mutex before its
consumer; `with_dispatch_boundary` still retains it across the bounded local
entry. No deadline, lease lifetime, binding or revocation policy changes.

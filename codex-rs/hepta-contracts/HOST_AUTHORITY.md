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
fsyncs the retained directory. Lock identity is rechecked after acquisition.
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
BOOTTIME includes suspended time. Each timestamp is CAS-persisted and fsynced
before being returned. A wall-clock reading below the retained highwater,
backwards BOOTTIME within one boot, invalid samples or arithmetic overflow
fail closed. After reboot, realtime must reach the previous boot's highwater;
opening never resets that value. It cannot detect a whole-host snapshot that
restores both the protected frontier and OS time. Root and the OS remain trusted.

Clock tests cover actual Linux sampling and reopen, a retained future watermark
that refuses to reopen without rewriting state, and projection/reboot/rollback
boundaries.

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

# Signed admission and durable replay

`SignedMessageClaims::signing_bytes` binds the issuer, key epoch, message and
subject IDs, routing scope, payload, sequence and expiry under a versioned domain.
The host obtains `IssuerRegistration` from its trusted identity store and refreshes
revocation state for every admission; registration from the incoming message is
not trusted. `SignedMessage::authenticate` performs strict Ed25519 verification
and returns a privately constructed `AuthenticatedMessage`. The old
`PreverifiedAuthEnvelope` API remains a reference replay model for already
verified input and does not authenticate signatures.

A durable host calls `HeptaEvidenceStore::admit_authbus_message` directly. The
existing evidence database owns migration 0009 and the replay table. Its immediate
SQLite transaction checks current time after waiting for the write lock, verifies
the signature and expected routing scope/payload, and advances a bounded replay
sequence before returning a receipt. Issuer/epoch/subject/scope keys are isolated;
fixed-width big-endian integers preserve the whole u64 sequence range. Repeated
or lower sequences fail across independent handles and database reopen. A failed
signature or capacity check leaves the sequence available for a valid retry.

This admission proves message identity and replay consumption. Quota allocation,
effect-specific policy and the kernel's final-use token remain separate checks.
No model, network, filesystem, selection or promotion authority is granted by the
receipt. It remains ordinary evidence data, not an unforgeable capability. The
issuer registration is a snapshot: a queued admission refreshes time after the
SQLite lock, but final-use authorization must also refresh revocation/epoch.
Commit-before-response failure consumes the sequence, so this is at-most-once
admission, not durable message delivery. The host's trust provisioning, replay-key
retirement and backup rollback protection are not created by this API.

Run `just test -p codex-hepta-authbus -p codex-hepta-evidence` for signed-field
substitution, expiry/revocation, real SQLite reopen, two-handle contention and
capacity rollback regressions.

## Durable message delivery

For recoverable delivery the host calls
`HeptaEvidenceStore::enqueue_authbus_message` **instead of**
`admit_authbus_message`. A receipt from direct admission cannot be upgraded:
its sequence is already consumed. Migration 0010 uses the same evidence SQLite
owner; one `BEGIN IMMEDIATE` verifies the actual bounded payload, signature,
host-selected subject/scope and time, advances the existing replay high-water,
and inserts an immutable message. Any insertion/capacity failure rolls all of
that back. No second writer or database is introduced.

The delivery ID is the authenticated envelope digest, which binds all signed
claims and the signature. An exact retained duplicate enqueue returns its
current status, including after a committed response was lost. Reuse of a
retained issuer/epoch/message ID with different content fails. Signatures and
current registration are still checked on enqueue retries. A consumed sequence
whose terminal history has been pruned returns `Replay`; status returns
`NotFound` (absent or pruned), never a fabricated historical acknowledgement.

The host scans `pending_authbus_deliveries(subject, scope, limit)` (1–128 rows),
resolves each returned issuer/epoch in its trusted current registry, and calls
`claim_authbus_delivery`. An available message or expired lease can be claimed
by one worker across independent handles/processes. The owner checks time after
the SQLite lock, reauthenticates the immutable message and caps the lease at its
signed expiry. Each claim, renew, retry, ack or terminal transition increments a
fence. Renew/retry/ack require the exact unexpired owner-issued lease; old fences
are rejected. Clock regression behind that row's last update fails closed.
For one configured issuer, `pending_authbus_deliveries_for_issuer` filters issuer
and epoch before `LIMIT`, so other epochs cannot hide eligible pending messages.
The existing mixed-issuer scan remains available; selection does not revoke rows.

Every worker operation needs fresh issuer registration; queue contents never
supply trust. Observed expiry becomes `Expired`; revoked/invalid signatures or
exhausted delivery attempts become `Quarantined`. The host calls
`quarantine_authbus_issuer` when its registry revokes an epoch, including messages
which no worker will claim. Key rotation alone does not invent a revocation
policy for other epochs. Registration remains a host snapshot; final external
use still needs current policy and revocation checks.
`quarantine_authbus_delivery(issuer, lease)` stops one leased delivery using the
current issuer and lease fence. It records a terminal outcome without ack and
does not retire other active messages belonging to that issuer.

Bounds are 4,096 total rows, 16 KiB payload per row (at most 64 MiB payload),
16 claims per message, 60 seconds per lease and 60 seconds per retry delay.
Expiry is swept on enqueue/recovery scans. Terminal records (`Acked`, `Expired`,
`Quarantined`) retain at most 1,024 rows or 24 hours and can be pruned earlier
under queue pressure. The DB forbids deleting active queued/leased messages.
Replay high-water rows are never pruned by this policy: their separate 16,384-key
bound can still reject new identities until a separately defined safe registry
retirement policy exists. Quarantine and expiry are terminal outcomes, not ack.

Only exact retained enqueue is idempotent. After a lost ack response, inspect
status: `Acked` plus the acknowledgement digest records the local commit;
repeating ack returns `Unavailable`. A lost claim/renew response requires waiting
for its lease to expire and claiming a new fence. A lost retry response can be
resolved by status or the pending scan. No API assumes a timed-out response means
the transaction did not commit.

Delivery is **at least once within expiry and the bounded attempt policy**;
expiration, quarantine and capacity are explicit limits, not guaranteed eventual
delivery. A crash after sending but before ack can resend the same delivery ID.
The consumer must durably deduplicate that ID and apply its own effect-specific
idempotency/final-use/reconciliation protocol. Message ack is ordinary consumer
evidence, not proof an external effect occurred. Never use message retry to
resend an unknown provider effect: existing indeterminate-effect quarantine
remains in force. This API neither claims exactly-once external effects nor
supplies a production message dispatcher, managed key host or backup anti-rollback
oracle. Native tests exercise real SQLite and an abrupt child-process exit
between send and ack.
Agentd provides a separately configured, restricted [signed text queue host](../hepta-agentd/AUTHBUS_TEXT.md)
using this library and the existing App Server queue; it is not a general effect dispatcher.

## Explicit PQ-only authority domains

The owner selects `AuthBusAlgorithm::MlDsa65V2`; signature bytes and wire fields
cannot select a weaker verifier. The implementation uses the existing
`hepta-contracts::pq_auth` ML-DSA-65 provider and its canonical SPKI format.
Message, time and settlement claims have separate PQ v2 signing domains. A
classic signature, a PQ signature over a classic preimage, or the wrong profile
is rejected without a second verification attempt.

`AuthBusAuthorityStore::open_pq` and `AuthBusAuthorityHost::open_pq` persist an
immutable authority profile. A classical database cannot be relabeled as PQ;
the owner must provision a new domain and independently retained checkpoint.
Migrations preserve existing classical issuers and outbox rows. They do not
invent PQ registrations or copy signatures into the new profile.

The evidence owner calls `bind_authbus_profile(MlDsa65V2)` before its initial
checkpoint. `pin_authbus_issuer` records the current PQ public key, key epoch,
revocation state and wall-clock floor. A same-epoch key substitution, earlier
epoch, revoked-to-active transition within an epoch, or clock rollback is
rejected. Issuer changes participate in the replay checkpoint handshake. The
consumer rechecks the persisted issuer inside its write transaction; the caller
must publish a pending checkpoint before dispatch.

Replay retirement carries the registry's exact verifying key and a separate PQ
retirement digest domain. The Evidence owner accepts it only against its pinned
revoked PQ issuer; a proof from a classical or different-key authority cannot
tombstone the same named epoch. The current floor retains one key per issuer,
so PQ operators must revoke, retire replay state and synchronize the checkpoint
before moving that floor to a new epoch. Retiring a prior epoch after that move
requires a future authenticated key-history design and currently fails closed.

Agentd's existing text trust file uses `schema_version: 2` and a canonical
1,974-byte SPKI encoded as hexadecimal in `public_key_hex`. Requests use
`auth_version: 2`. `sign_authbus_text_pq` signs this same wire using an
independently supplied custody key. Agentd reloads its private owner file before
each admission and dispatch stage, pins the current issuer, and synchronizes the
external checkpoint. Replacing the file with a valid classical key does not
downgrade an activated domain. A missing wire version retains the historical
v1 meaning and is rejected by a PQ owner.

PQ signatures occupy exactly 3,309 bytes (6,618 hexadecimal characters on the
text control wire). Outbox payloads remain capped at 16 KiB, the existing
control frame at 65,536 bytes, and a PQ message's remaining lifetime at five
minutes. The existing row, issuer, attempt, replay and lease limits still apply.
These are admission bounds, not a measured throughput claim.

## Authenticated time and freshness

A PQ time issuer signs the owner's exact one-use challenge. Challenges are
persisted, bounded to 256 outstanding entries and expire after 30 seconds.
The observed time must be within five seconds of the owner's local clock.
Challenge consumption, current issuer verification and floor advancement share
one transaction. A sample's deadline is persisted and checked again before
authority transactions commit; restoring a time floor does not renew freshness.
The Bao evidence-provider interface passes these challenges through the existing
authorization, dispatch and settlement calls.

This clock policy assumes the owner's local clock is an independent usable
reference. A valid ML-DSA signature does not prove UTC accuracy. Deployments with
larger clock disagreement fail closed and need explicit clock repair.

Settlement resolves the current registered issuer under the same SQLite write
transaction as quota accounting. A registration snapshot obtained before an
await cannot bypass a later revocation or rotation. Recovery checks recompute
the semantic frontier even when checkpoint metadata itself appears unchanged.

This profile covers the AuthBus paths described above. It does not convert
other application authority formats, network peer authentication, TLS key
exchange, or proof systems into PQ security. A remaining classic-only caller
is refused in a PQ AuthBus domain and must be migrated explicitly.

In particular, the active Agentd Objective/RunStart V1 path still persists a
64-byte classical signature in its journal. Submission, recovery and final
runtime revalidation explicitly reject that format under a PQ owner profile.
Its asynchronous trust refresh uses the same durable floor and checkpoint
handshake; it has no synchronous file-only bypass. A new RunStart wire, signing
domain and journal version remain prerequisites for claiming PQ objective
execution. The unregistered legacy `objective_ingress` / `objective_dispatch`
source files are not part of the active product path or the migrated coverage.

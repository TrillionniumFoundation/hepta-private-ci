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

# `auth.authbus` current implementation

## Current executable contract

`codex-rs/hepta-authbus` verifies issuer-bound Ed25519 messages. The host supplies
trusted issuer registration, current revocation and expected scope/payload.
`SignedMessage::authenticate` checks the signature, issuer/key epoch, expiry,
scope and payload and returns a privately constructed `AuthenticatedMessage`.
Authentication alone does not consume a durable replay sequence.

`HeptaEvidenceStore::admit_authbus_message` authenticates and consumes the sequence
inside one immediate SQLite transaction. The replay key is `(issuer, key epoch,
subject, scope digest)`; sequences must increase, and new keys are bounded at
16,384. Time is checked after acquiring the write lock. A receipt returns only
after commit succeeds; failed authentication or capacity admission consumes
nothing. Receipts carry `AuthorityPosture::DENY_ALL`.

For durable delivery, `enqueue_authbus_message` replaces direct admission and
atomically commits the replay advance plus an immutable message. The same
`HeptaEvidenceStore` provides bounded recovery scanning, claim, renew, retry, ack,
status and explicit revoked-issuer quarantine. Every worker transition rechecks
issuer registration and expiry; a new fence invalidates the old lease. Active
messages cannot be pruned. Terminal history is bounded independently of replay.
A send followed by a crash before ack can deliver the same ID twice; consumers
must deduplicate and retain their separate final-use/effect reconciliation rules.

The legacy `PreverifiedAuthEnvelope` / `ReplayWindow` API still accepts already
verified facts and records sequences only in process memory. It does not verify
signatures or become durable through the addition of the signed API.

The current source candidate also supplies durable control state through the
existing `HeptaEvidenceStore`. `install_authbus_policy` stores immutable policy
versions and a monotonic head; `authorize_authbus` binds principal, action,
resource, scope, audience, exact payload digest and expected policy revision.
`install_authbus_quota` owns integer capacity/reserved/consumed state.
`reserve_authbus_quota` rechecks the current policy head and quota revision
inside one immediate write transaction before holding capacity. Reservations
transition through Active, Settled, Cancelled, Expired and Quarantined; expiry
and quarantine keep quota held until explicit reconciliation proves no effect or
supplies observed cost.

The qualification provider seam
`dispatch_provider_effect_with_authbus_qualification` performs authorize then
reserve before entering the existing durable provider-effect boundary. Provider
Completed does not itself settle quota: `reconcile_authbus_provider_effect`
requires separate `ObservedCostEvidence`. Rejected/no-dispatch evidence can
release the hold; unknown/accepted outcomes remain held. This seam is not a
production provider caller.

## Public symbols and source bindings

- `IssuerRegistration`, `SignedMessageClaims::signing_bytes`,
  `SignedMessage::authenticate`, `AuthenticatedMessage`: authbus `src/signed.rs`;
- `PreverifiedAuthEnvelope`, `TrustedReplayContext`, `ReplayWindow`,
  `VerificationReceipt`, `Error`: authbus `src/lib.rs`;
- `HeptaEvidenceStore::admit_authbus_message`, `AuthBusAdmissionError`:
  evidence `src/authbus_store.rs`;
- outbox APIs and records: evidence `src/authbus_outbox.rs`,
  `src/authbus_outbox_worker.rs`, `src/authbus_outbox_record.rs`;
- replay and outbox tables: evidence migrations `0009` and `0010`.

## Durability and activation

The evidence-store admission path preserves replay state across independent
handles and database reopen. Legacy replay state is lost on restart. The host
must compose trusted issuer registration and the evidence-store API; production
enrollment is not established by library tests. Neither path grants effect
authority.

## Target-only design

The following remain outside the repository-controlled source closure: an
independently governed trust root/key ceremony, an independently retained
rollback checkpoint or monotonic hardware/remote anchor, a production effect
caller, real provider/operator consent, target-host capacity acceptance and
operator promotion/release. The repository now contains managed issuer
enrollment/revocation/rotation/retirement, a rollback hash-chain plus external
checkpoint verification API, durable policy/quota/reservation control and the
qualification effect composition. Those source capabilities do not self-close
the external gates.

## Known limits and non-claims

Issuer registration must come from the host trust store, never the incoming
message. Current time uses the host clock; SQLite persistence is not protection
against restoration of an older database. No managed key host or distributed
replay coordinator is provided. In the legacy API, a nonzero `signature_digest`
is only a reference, and constructing `TrustedReplayContext` does not authenticate
its contents.

## Verification

`signed_tests.rs` covers signed-field substitution, key epoch, revocation,
expiry and scope. Evidence `authbus_store_tests.rs` covers real SQLite reopen,
the full unsigned sequence range, two-handle contention and failed-admission
retry. `authbus_outbox_tests.rs` covers atomic insertion rollback, retained
duplicate admission, competing leases, stale fences, bounded terminal retention
and actual process exit after send before ack. Legacy `lib_tests.rs` covers replay partitioning, capacity, trusted-context
validation and deny-all authority. Run `just test -p codex-hepta-authbus
-p codex-hepta-evidence` for native execution; source anchors only establish test
presence.

## Integration prerequisites

The host must supply protected trust configuration and current revocation, use the durable admission API where replay must survive restart, retain the current rollback checkpoint independently of the SQLite backup, and govern trusted time/restore. Agentd reconciles its trust file into the managed issuer registry. Effect adapters must use an authorization decision plus reservation and still perform their final-use authority check; no effect adapter may consume `VerificationReceipt` as a grant. See
[`SIGNED_ADMISSION.md`](../../../codex-rs/hepta-authbus/SIGNED_ADMISSION.md) and the
separate legacy [`PREVERIFIED_REPLAY_V1.md`](PREVERIFIED_REPLAY_V1.md) contract.

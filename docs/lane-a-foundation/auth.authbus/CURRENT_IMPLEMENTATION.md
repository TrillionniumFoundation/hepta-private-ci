# `auth.authbus` current implementation

## Current executable contract

The candidate keeps signed authentication and effect authority separate. `codex-rs/hepta-authbus`
verifies issuer-bound Ed25519 messages and exports the typed policy/quota/reservation
domain records. Successful authentication still returns only ordinary evidence with
`AuthorityPosture::DENY_ALL`; it is not an effect grant.

The durable owner is the existing `HeptaEvidenceStore`. Migrations 0009/0010 retain
signed replay and durable message delivery. Migration 0011 adds versioned policy
history/current heads, quota registry/history, reservation state, monotonic host-trust
heads, permanent replay-epoch retirement markers and the local replay-checkpoint
projection. Store open verifies quota conservation against every reservation that still
holds quota.

## Authorization, quota and reservation control

`HeptaEvidenceStore::put_auth_policy` accepts monotonic policy revisions. Reusing a
revision with different content conflicts; `authorize` requires the caller's exact
expected revision and fails closed when the policy is missing, stale or denied.

`put_quota_registry` stores exact unsigned integer capacity and counters. The owner
serializes changes with `BEGIN IMMEDIATE`; `authorize_and_reserve` checks policy and
quota and commits the reservation plus reserved counter in one transaction. Identical
operation IDs are idempotent; changed semantics conflict. No floating-point quota
arithmetic is used.

Reservation transitions are `Reserved -> InFlight -> Settled|Quarantined`, with
`Reserved -> Cancelled|Expired` and `Quarantined -> Settled|Cancelled` reconciliation.
Only `Reserved` can expire automatically. Once `begin_reserved_effect` marks a
reservation in flight, expiry never implies that no effect occurred. Unknown outcomes
retain quota in `Quarantined` until a terminal observation proves settlement or
non-application. Settlement releases the full reservation and adds only the observed
cost to consumed quota.

Immediately before an effect seam, `begin_reserved_effect` rechecks the exact policy
revision. A stale or denied policy cancels a still-unstarted reservation and releases
its quota. The qualification-only provider facade
`dispatch_provider_effect_guarded_qualification` composes authorize+reserve before the
existing durable provider-effect journal; the old raw qualification dispatch is crate
private so an external caller cannot bypass this guard.

## Signed admission, replay and delivery

`SignedMessage::authenticate` checks signature, issuer/key epoch, expiry, scope and
payload. `admit_authbus_message` authenticates and consumes the sequence inside one
immediate SQLite transaction. The replay key is
`(issuer, key epoch, subject, scope digest)`; sequences increase monotonically and the
active registry remains bounded at 16,384 keys.

`enqueue_authbus_message` atomically commits replay advance plus immutable payload.
Recovery scanning, claim, renew, retry, acknowledgement and quarantine retain the
existing fenced-lease semantics. A send followed by a crash before acknowledgement can
still deliver the same ID twice; consumers must deduplicate and reconcile their own
external effects.

Replay compaction is no longer a raw delete. `retire_authbus_replay_epoch` requires an
exact externally retained checkpoint, a retired/revoked old epoch, and zero active
outbox rows. It writes a permanent retired-epoch marker before deleting the old
high-water rows; later admission for that epoch remains rejected. The checkpoint
contains a deterministic digest of the complete durable replay registry and a monotonic
generation.

## Host trust lifecycle

Agentd signed-text trust uses schema version 2. Every projection carries a monotonic
`trust_revision`; the evidence owner persists the current trust head and rejects
revision rollback, epoch rollback, same-epoch key substitution, revoked-to-live
rollback and any same-revision change to the complete trust projection. The projection
digest covers issuer, key epoch/key, revoked state, thread allowlist and optional replay
checkpoint.

Agentd can load the expected replay checkpoint from `--authbus-replay-checkpoint-file`. The protected file must be outside the Agent home and run root and is verified on every admission/dispatch trust refresh as a rollback watermark. Normal replay growth after the checkpoint is allowed; restoring a database whose stored checkpoint predecessor is older than the independently retained expected checkpoint fails closed. A checkpoint stored only with the same backup/restore set as SQLite is not an independent anti-rollback oracle.

## Public source bindings

- protocol/domain types and signed authentication:
  `codex-rs/hepta-authbus/src/{lib.rs,control.rs,signed.rs}`;
- durable replay:
  `codex-rs/hepta-evidence/src/authbus_store.rs`;
- durable policy/quota/reservation/checkpoint state:
  `codex-rs/hepta-evidence/src/authbus_control.rs`;
- guarded provider qualification facade:
  `codex-rs/hepta-evidence/src/authbus_provider_guard.rs`;
- durable delivery:
  `codex-rs/hepta-evidence/src/authbus_outbox*.rs`;
- Agentd trust/ingress/relay:
  `codex-rs/hepta-agentd/src/authbus_{trust,ingress,dispatch}.rs`;
- migrations: evidence `0009`, `0010`, `0011`.

## Verification

`authbus_control_tests.rs` executes BUS-01 through BUS-04 against real SQLite:
simultaneous last-unit reservation, idempotent/conflicting settlement, expiry racing a
terminal result, and stale-policy fencing before the effect boundary. It also covers
crash/reopen reconciliation, replay-checkpoint drift detection and safe retired-epoch
compaction.

The qualification crate now requires every negative case to carry one identical
execution provenance tuple: exact source SHA, source tree, executable digest, command
digest, runner identity, execution interval and zero exit code. Mixed source/binary
evidence and failed execution are rejected.

Lane A CI explicitly runs `codex-hepta-agentd --test authbus_text_product` for the
exact source head and deterministic synthetic merge and retains its command record next
to the Lane A source/native receipts.

## Remaining non-claims

This candidate does not by itself establish independent semantic/security acceptance,
a named production provider-effect adapter, operator acceptance, canary, promotion or
release. The Agentd signed-text path is a real narrow host integration, not general
provider authority. The guarded provider facade remains qualification-only until a
named production effect caller is activated.

The optional replay checkpoint becomes rollback protection only when its expected value
is independently retained and governed. Managed private signing-key custody/rotation
remains an operator/issuer responsibility; Agentd only accepts the protected public
trust projection and never generates an issuer key.

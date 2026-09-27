# `auth.authbus` current implementation

## Candidate status

The current branch is a source candidate under exact-head qualification. It is
not activated and does not claim release evidence. The normative activation
state is recorded in `docs/modules/auth.authbus/ACTIVATION_DECISION.md`.

The candidate contains two deliberately separate AuthBus owners:

1. signed-message replay/outbox state in the existing evidence SQLite owner;
2. policy, issuer, trusted-time, quota, reservation, settlement and rollback
   state in `AuthBusAuthorityHost`.

Neither surface grants provider authority merely because authentication or
policy evaluation succeeded.

## Closed trust boundary

`IssuerRegistration` and `SettlementIssuerRegistration` are sealed handles.
Their verification key, issuer identity, purpose, epoch and revocation state are
not publicly writable. Message handles are resolved either from the durable
AuthBus issuer registry or from an owner-controlled persisted private registry
that is checked for canonical path, ownership, mode, regular-file identity,
single link, size and replacement drift. Settlement handles are resolved only
from the durable registry.

Settlement does not trust a previously returned handle as current authority.
Inside the same settlement transaction, it reloads the exact
`(issuer_id, Settlement purpose, key_epoch)` record and applies the current
revocation state before signature verification. A message-purpose key cannot be
substituted for settlement, and a stale handle stops working immediately after
revocation.

`AuthBusAuthorityStore` is crate-private. External callers cannot instantiate a
raw writer or skip checkpoint publication. The public mutation surface is
`AuthBusAuthorityHost`; read-only result types remain public. The generated
closed-world inventory is
`docs/modules/auth.authbus/PUBLIC_API_INVENTORY.json`, enforced by
`scripts/check-authbus-closed-world.py`.

## Signed ingress and durable replay

`SignedMessage::authenticate` binds issuer/key epoch, message, subject, scope,
payload, sequence and expiry using Ed25519. Authentication consumes no durable
replay state by itself. `HeptaEvidenceStore::admit_authbus_message` and
`enqueue_authbus_message` perform durable replay advancement and immutable
outbox insertion under the evidence SQLite owner.

Agentd reloads its private persisted issuer registry at admission and delivery
boundaries. Production-configured ingress also uses an independently retained
replay checkpoint outside the Agent home. Local pending state is published to
the external witness by write, file fsync, atomic rename and directory fsync
before local promotion. Restoring only an older evidence database therefore
fails closed.

## Authority owner and single-writer fencing

`AuthBusAuthorityHost` owns durable policy revisions, issuer lifecycle,
trusted-time floor, quota registry, reservation state, settlement and the
external authority checkpoint. `open` requires both an existing database and
matching existing checkpoint. `bootstrap` is valid only when neither state
domain exists; it is not a witness-reconstruction path.

Before opening or recovering the authority database, the host acquires a
process-lifetime cross-process owner fence backed by an independent SQLite lock
database and an exclusive transaction. A second process fails closed. Process
exit, including `SIGKILL`, closes the connection and releases the OS-managed
lock. Checkpoint compare, publish and local promotion occur while the owner
fence is held.

The authority database uses WAL, `synchronous=FULL`, foreign keys, ordered
migrations, live-schema comparison against the compiled migrations,
post-migration `quick_check`, and post-migration foreign-key validation.
Authoritative mutations mark the semantic frontier dirty in the same commit.
The host publishes exactly one successor external checkpoint before returning a
successful mutation.

## Trusted time, policy and quota

`TrustedTimeSample` is opaque outside the crate. It is produced only by
verification of a signed attestation from an active `TrustedTime` issuer and
binds wall time, monotonic source revision and source digest.

Policy decisions bind policy identity/revision, principal, action, scope and
trusted time. They retain `AuthorityPosture::DENY_ALL`; they permit a reservation
decision but do not mint final-use authority.

Quota accounting uses checked
`available + reserved + consumed == limit` semantics. A reservation binds the
stable operation ID, quota, amount, effect digest, policy identity/revision and
decision digest. The lifecycle is:

```text
Held -> DispatchAttempted -> {Indeterminate, Settled, Released}
Held -> {Cancelled, Expired}
```

`DispatchAttempted` is persisted immediately before the external-effect
boundary. A timeout, lost response or crash after that fence is never treated as
`NotApplied`; restart converts the row to `Indeterminate`, and its quota remains
held until authenticated terminal evidence arrives.

## Bounded recovery and authority worker

Startup performs only a bounded restart-reconciliation batch and one bounded
expired-reservation batch. If more work remains, write admission stays
fail-closed through durable `recovery_required` state. It does not run an
unbounded startup loop.

`AuthBusAuthorityWorker` is the single periodic maintenance owner. Each tick:

1. obtains a freshly verified trusted-time sample from its caller;
2. runs bounded restart reconciliation;
3. refunds expired undispatched holds and marks expired attempted effects
   indeterminate in a bounded batch;
4. publishes the resulting authority checkpoint;
5. emits `AuthBusOperationalSnapshot`, SLO evaluation and alerts.

The worker skips missed intervals instead of accumulating an unbounded backlog.
Observer/export failure terminates the loop rather than silently discarding
safety signals.

## Product composition

`BaoClient::consume_kv_v2_with_authbus` is the current source-composed external
effect path. It combines a caller-supplied durable operation identity, policy
and quota reservation, exact final-use binding, durable dispatch fencing,
final-use-protected HTTPS execution and independently signed settlement
evidence. Timeout, transport loss and ambiguous provider outcomes preserve the
reservation as indeterminate.

Agentd is the named signed-ingress/outbox product caller. Evidence outbox
quarantine, claim, renew, retry and acknowledgement require a current sealed
issuer handle. Wrong epoch and revoked registrations preserve queue state and
cannot manufacture quarantine authority.

The legacy `PreverifiedAuthEnvelope` / `ReplayWindow` surface remains only as an
in-process compatibility API. It does not authenticate a signature, survive
restart, reserve quota or grant effect authority.

## Source bindings

- sealed message admission: `codex-rs/hepta-authbus/src/{signed,issuer_registry}.rs`;
- durable issuer and trusted-time registry:
  `codex-rs/hepta-authbus/src/{trust,trust_store}.rs`;
- public owner and single-owner fence:
  `codex-rs/hepta-authbus/src/{host,owner_fence}.rs`;
- policy/quota/reservation/settlement:
  `codex-rs/hepta-authbus/src/{authority_store,quota_store,settlement_store}.rs`;
- recovery/checkpoint/schema:
  `codex-rs/hepta-authbus/src/{recovery,authority_schema}.rs`;
- maintenance, SLO and alerts:
  `codex-rs/hepta-authbus/src/{operations,worker}.rs`;
- durable signed ingress/outbox:
  `codex-rs/hepta-evidence/src/authbus_{store,outbox,outbox_worker,recovery}.rs`;
- Agentd composition:
  `codex-rs/hepta-agentd/src/{authbus_ingress,authbus_dispatch,authbus_trust,evidence_trust}.rs`;
- provider composition:
  `codex-rs/hepta-bao-adapter/src/https_consumer.rs`.

## Executable qualification

`codex-hepta-authbus-p1-3-qualification` now executes modern host behavior in
addition to the legacy replay matrix. It covers persisted-registry signature
verification, forged key, revoked key, epoch substitution, purpose isolation,
owner collision, bounded expiration sweep, dispatch fencing and authenticated
settlement. Product-specific quarantine and Bao/Agentd execution remain in the
owner crates to avoid circular dependencies and are run by the same AuthBus
qualification workflow.

`.github/workflows/authbus-authority-qualification.yml` checks the exact source
head and deterministic pull-request merge candidate. It requires:

- generated closed-world API inventory;
- formatting;
- AuthBus, qualification, evidence, Agentd and Bao product tests;
- full workspace all-target regression;
- strict all-feature Clippy for the affected packages;
- clean tracked worktree;
- a receipt binding commit, tree, migration/schema digest, Cargo lock digest,
  test-log digests and build-artifact digest.

Cancellation, skip, queue state, a static-only check or evidence from another
SHA is not success.

## Operations and documentation

The module-owned operational contract is under `docs/modules/auth.authbus`:

- `THREAT_MODEL.md`;
- `OPERATIONS.md`;
- `SLO.md`;
- `RECOVERY.md`;
- `KEY_ROTATION.md`;
- `SCHEMA_COMPATIBILITY.md`;
- `PROVIDER_AND_DEPLOYMENT.md`;
- `DASHBOARD.json` and `ALERTS.json`;
- `SECURITY_REVIEW.md` and `ACTIVATION_DECISION.md`.

## Remaining external gates and non-claims

The repository candidate does not by itself prove that a production operator
has provisioned independent checkpoint storage, non-exportable KMS/HSM keys,
trusted-time service, target-host disk semantics or an external durable
`kernel.operations` owner. Distributed multi-host AuthBus consensus is not
implemented; the supported model is one active authority owner per database.

Production activation remains blocked until one unchanged candidate obtains
terminal-success source-head and synthetic-merge receipts, target-host ENOSPC
and power-loss evidence, KMS/operator acceptance and independent release
approval. An indeterminate reservation is never automatically refunded merely
to restore availability.

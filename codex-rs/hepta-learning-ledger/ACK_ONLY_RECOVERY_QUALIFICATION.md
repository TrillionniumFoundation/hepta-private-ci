# Source-bound ACK-only recovery — qualification feature only

Base: hepta-private-ci@78fdb0cf8537e3a84fc6e0a849707559c80881e8
Release: DRAFT / DO NOT DEPLOY / production HOLD

## Actual problem

Original Canonical LedgerWriter can durably commit an authenticated
Decision/Outcome before a separate LedgerWitnessStore ACK becomes
durable. A genuine signed event may be one record ahead of Witness
when the original Generator/Observer signature later expires.
Backdating caller wall time to replay the historical event is NOT
authorized production recovery, and deleting the durable event is
also incorrect.

LedgerWitnessStore.advance validates storage mechanics; it is
NOT a product root-authorized RecoveryAuthority interface.

## Isolated Rust implementation

Source: src/ack_only_recovery.rs.
Feature: qualification-ack-only-recovery, DEFAULT OFF.

No existing LearningEvidenceRoleV1 signing tag, production API, ledger
serialization or root trust distribution is changed.

A separate qualification namespace defines:
- AckOnlyRootPinV1: product-host PINNED root key, binding, objective,
  validity and revocation. The caller's own self-signed root does not
  establish product enrollment.
- AckOnlyRootDelegationV1: root-signed separate recovery and escrow
  credentials, controller identities, epoch, validity and public keys.
- AckOnlyCurrentRevocationCutV1: root-signed fresh current delegation
  state, original-event-not-revoked assertion, checked within 30s.
- AckOnlySourceEscrowV1: delegated escrow-signed ORIGINAL preappend
  event, authentication digest, original source-time issuance,
  event/record digest, prior witness anchor, next ledger anchor and
  claimed durable source-time escrow issuance.
- AckOnlyRecoveryGrantV1: delegated RecoveryAuthority-signed
  one-target grant nonce, exact escrow receipt digest, current cut,
  specific record ID / event digest, old/new chain anchors, objective
  and original actor auth digest, valid for at most 90s.
- reconcile_one_existing_ack_qualification: checks the entire root,
  role, signature, source-escrow and grant chain BEFORE any write.
  It allows exactly ONE already-existing authenticated V2 event to
  be ahead of the original independent Witness, validates original
  objective, actor controller independence and byte-equal escrow
  receipt, then calls WitnessStore.advance to ACK that exact source
  record. It NEVER calls DurableLedger.append.

Already ACKed replay, Legacy V1 events, >1 unwitnessed events,
wrong event/record/predecessor, forged Root, wrong independent
controller, revoked cut, expired grant, missing/altered escrow bytes
and new event creation are all rejected by qualification tests.

## Truth and limitations

This code is isolated and NOT enabled by the default Cargo feature
selection. All new keys and event examples in native unit tests
are SYNTHETIC fixture material. A valid signature from these fixtures
does NOT prove independent Mac/X230 custody, remote fsync, an original
source-time Escrow record or product/root enrollment.

An independent caller-provided receipt byte array and self-reported
source-time timestamp cannot prove physical provenance or real
preappend persistence by themselves. Those are explicit external
product-host obligations. This code's positive path is qualification
only, not an authorized production recovery grant.

The original real EUR/USD IB PAPER test ledger from Phase4L has NO
independent source-time Escrow; it must not be retroactively accepted
as having one. The original opaque LLM complete action population,
true action probabilities, actual broker fills/cost-complete PnL,
independent product Root, signed market-eligible DatasetSnapshotV3,
Artifact Owner CURRENT and actual sudden-power recovery remain HOLD.

Required production follow-up: independent root/custody ceremony,
current trusted monotonic clock and revocation cut, native approved
RecoveryAuthority migration, external original preappend Escrow
archive verified by originating host, persistent one-use grant nonce
and writer fencing, complete Outcome restart/power-cut tests, and
the exact old-event ACK-only no-new-ledger guarantee.

## Tests

DEFAULT Cargo (feature OFF):
- original Ledger 118 passed
- original Artifacts 92 passed
- two ignored, zero failed

OPT-IN qualification Cargo (feature ON):
- Ledger 133 passed (15 new scoped tests)
- Artifacts 92 passed
- two ignored, zero failed

The previously misleading cold-reopen assertion was removed from
the test count; a native fully qualified Outcome cold-reopen is
NOT claimed. Exact original Cargo.lock is unchanged.

Do not install this qualification feature or promote models based on
its synthetic keys/tests. Keep the security review and product release
status HOLD.

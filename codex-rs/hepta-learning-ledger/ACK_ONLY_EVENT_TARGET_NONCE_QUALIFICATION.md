# Phase 4R — reserve original event target BEFORE recovery grant nonce

Date: 2026-10-12. Canonical stacked Draft only, on PR #1580,
parent commit 3b91cb1c98f084eb396644e224a290287fecb059.
Release: HOLD. Qualification feature DEFAULT OFF.

## Original concrete bug

The parent qualification ACK-only recovery implementation wrote ONE
O_EXCL, fsynced owner-local reservation named by the RecoveryGrant nonce.
Although an identical nonce would be rejected, a RecoveryAuthority
could sign a DIFFERENT valid recovery grant with a NEW nonce for
the SAME immutable Ledger event and the SAME previous Witness frontier.
Both grants were eligible to reserve different names in the single
owner directory. The later native Witness check might refuse a
second ACK, but durable recovery authorization was not unique by
the actual Ledger target, and a crash could leave contradictory
recovery grants concurrently reserved.

This is a genuine local recovery journal identity defect, not
proof of a remote host or product trust issue.

## Exact test-only fix

Only the existing feature-gated ACK-only module is changed.
No original Canonical Ledger encoding, existing signed actor policy,
production root registration, Service binary or product trading
policy is modified.

The existing AckOnlyGrantNonceJournalV1 is now a TWO-record,
FAIL-CLOSED reservation:

1. Validate root-signed delegation, current revocation cut,
   original preappend escrow bytes, source actor, exact existing
   Ledger event/record digest and Witness pre/post anchors, then
   inspect the original owner-pinned directory FD.
2. Compute an event-target key in a distinct domain over the
   original Ledger binding, objective, original authentication
   digest, original record stable ID, exact previous Witness
   sequence+chain, intended next sequence+chain, and original
   immutable event digest. The target key intentionally EXCLUDES
   grant ID, nonce, original issuance time and signature.
3. Create a target-<SHA256> file using the same already-open
   owner-pinned safe rustix openat directory FD, O_EXCL,
   O_NOFOLLOW, O_CLOEXEC, mode 0600. Store the exact target,
   chosen nonce, original signed grant-body hash and detached
   RecoveryGrant signature, file fsync and directory fsync.
   Already-existing target: EventAlreadyReservedOrIndeterminate.
4. ONLY AFTER target fsync, create a second nonce-<nonce> file
   with O_EXCL and the same safe held dirfd. The second record
   also binds the target digest and original signed grant.
   File fsync and directory fsync both complete before the
   native WitnessStore is allowed to advance.
5. Re-check the original owner directory path to the held dirfd
   after both writes. Any path rebind, filesystem error, missing
   evidence, duplicate event/nonce, or incomplete write is HOLD.
   There is deliberately NO deletion, rollback, retry using a
   fresh nonce, or automatic reauthorization of an uncertain ACK.
6. The returned success receipt binds the persisted target and
   nonce bodies; only then may the earlier cryptographically
   validated and exactly constrained ACK-only function advance
   the existing independent Witness. It cannot append a new
   Ledger event.

This process preserves the original crate forbid(unsafe_code)
lint and requires no new Cargo dependencies or lockfile changes
beyond the already approved optional rustix entry in the parent.

## Actual native test failures and hard gates

Full native tests use local SYNTHETIC Root/Delegation/Escrow and
RecoveryGrant Ed25519 fixtures. They do not create new real broker
price labels, orders, eligible native training rows or true
independent signer credentials.

The added adversarial and positive tests prove:

- Same original event with TWO different, valid signed
  RecoveryGrant nonces: second target reservation fails BEFORE
  any Witness ACK, with unchanged original Ledger/Witness bytes.
- Same nonce with two different claimed source events:
  the second target reservation stays indeterminate, but the
  nonce reservation refuses cross-event duplicate use.
- A genuinely separate Rust process fsyncs ONLY the original
  event-target file, then exits with code 49 before nonce write.
  A new authorized-signed nonce after that process exit also
  fails; the original Ledger/Witness still has no new ACK.
- Two different Rust processes with differently signed test
  grant IDs/nonces are released from a common barrier to race
  in one owner directory; exactly ONE target+nonce pair
  persists, one process exits with the specific target-conflict
  rejection, and no Witness ACK is emitted.
- A separate two-thread test also permits exactly one event
  reservation despite distinct nonces.
- Both target and nonce artifacts are mode 0600 from creation,
  use distinct signed domain boundaries, retain the original
  test-only signed-grant evidence and cannot be overwritten.
- A pre-planted symlink at the deterministic target filename
  is rejected; a symlink at the nonce filename is likewise
  rejected. Neither follows/overwrites the external target.
- Exact directory-path rename/rebind between inode check and
  safe openat is detected; original opened FD receives the
  reservation but replacement attacker directory remains empty;
  the failed operation does not advance the Witness.
- Parent native tests for V2 authenticated terminal Outcome,
  root revocation and control-domain independence, exact
  cold-reopen by a distinct native Rust process, duplicate
  grant rejection, and code-47 process exit AFTER both writes
  before ACK still pass.

No electrical power interruption, independent Mac/X230 Escrow
signer, product hardware Root or global nonce owner has been
tested or fabricated by this branch.

## Release and root security boundaries

The owner nonce directory is still a LOCAL file store. An
attacker who can clone a fully independent nonce store on
another host may obtain two separately valid reservations.
This feature does NOT provide cross-host single-use consensus,
product-root-independent administration, root epoch/clock
attestation, fencing of multiple actual product Writers,
or recovery of an authority-revoked old actor after a true
sudden power cut.

The actual earlier EUR/USD IB PAPER test ledger had NO
independently escrowed source-time real product grant. It
cannot be retroactively promoted from its test-only price
label or from a mocked recovery signature.

Further product release requires independently root-enrolled
RecoveryAuthority and Escrow administrators, real durable
preappend source evidence, trusted current time/revocation,
one global nonce/event owner, owner fencing, actual power
interruption and after-cost broker PnL / eligible Dataset V3.

The original opaque LLM complete action opportunity/support
and actual selected behavior probabilities remain HOLD.
Do NOT deploy, switch on qualification feature, send orders,
advance old test Witnesses or promote any learned model.

# Phase 4Q — original Canonical nonce directory FD security hardening

Date: 2026-10-12
Parent: Canonical Draft PR #1576, commit c559deeff34ad6bea97f3956566c9cb3fee5ce2c.
Status: DRAFT / NOT DEPLOYABLE / feature DEFAULT OFF / production HOLD.

## Original directory race and safe fix

The Phase4P test-only AckOnlyGrantNonceJournalV1 verified its
owner-private nonce directory inode, owner UID, mode 0700 and
symlink status, then created its nonce file by resolving the
directory PATH again. A directory pathname could be renamed or
replaced between check and creation, redirecting a nonce grant
to an untrusted storage path. O_EXCL and fsync do not provide
one-use guarantees across such path redirection.

This branch changes the feature-gated implementation:

1. Open the original directory as a SAFE rustix directory
   file descriptor with DIRECTORY, NOFOLLOW and CLOEXEC,
   verify effective-user ownership, inode/dev/uid and mode
   before and after open, then sync the held directory FD.
2. Reserve the deterministic nonce filename via SAFE
   rustix::fs::openat relative to the held directory FD.
   Use O_EXCL | CREATE | NOFOLLOW | CLOEXEC and 0600 at
   creation. No nonce path is resolved by its original
   mutable pathname after the initial FD is pinned.
3. Fsync the created file, fsync the pinned original
   directory FD, then check the visible owner directory path
   against the held FD again. If it was replaced, HOLD:
   do not advance Witness, do not delete the nonce reservation
   and do not resample/reissue the RecoveryGrant.
4. Preserve the original Canonical crate-level
   forbid(unsafe_code). An initial raw libc syscall
   experiment was correctly rejected by the compiler.
   The final code uses safe rustix APIs and does NOT relax
   the original safety lint.

The original workspace already has rustix 1.1.4. The new
optional dependency is enabled ONLY under the existing
qualification-ack-only-recovery feature. Cargo.lock contains
ONE intentional extra package-dependency line for the native
ledger crate; no third-party version changed. Never describe
this lockfile as bit-identical to the parent commit.

## Deterministic TOCTOU and symlink refusal tests

A test-only hook runs exactly BETWEEN the original directory
identity precheck and openat. It renames the pinned owner
directory and creates a new replacement at the former path.
The nonce is created in the ORIGINAL open dirfd, not in the
attacker replacement. After the file and directory fsync, the
visible pathname no longer agrees with the held FD. The
qualified operation returns NonceStoreUnavailable; the
original Witness remains unchanged and no Ledger event is
added. This is a deterministic live test of the race,
not a speculative static code review.

A second native adversarial test plants a symlink at the
deterministic nonce filename; O_EXCL/NOFOLLOW refuses without
following it or overwriting an attacker's target.

All earlier synthetic native tests still cover original
typed V2 Outcome after prior Decision, exact ACK-only without
new Ledger event, duplicate grant refusal, separate-process
cold file readback, deliberate process exit after nonce
fsync before Witness advance, two-thread nonce competition,
signed root/cut/escrow/grant authority and actor separation,
original objective/event mismatch and Legacy V1 refusal.

These tests use synthetic local keys and events. They are
NOT the original trading LLM policy, an independent Mac/X230
root-approved producer, or real broker economic PnL.

## Remaining HARD HOLD

- The local pinned directory FD is NOT globally replicated
  or root-owned across independently cloned machines.
- No independently approved production RecoveryAuthority,
  Mac/X230 original preappend Escrow, hardware custody,
  physical remote fsync or power-fail test was achieved.
- No production trusted monotonic clock, current Root
  revocation cut, global nonce leasing/fencing, or formal
  indeterminate recovery Owner.
- No old opaque LLM complete support/actual action probability,
  real broker order/fill after-cost returns, market-eligible
  DatasetSnapshotV3 or Artifact Owner CURRENT.
- The original Phase4L real EUR/USD price-only two-record
  lab has NO real source-time independently held Escrow and
  cannot be retroactively made a product observation.

Do not install or enable this feature in a trading/learning
service. Keep the PR Draft and product qualification HOLD.

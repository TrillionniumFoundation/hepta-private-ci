# Phase 4P — V2 Outcome ACK-only recovery and durable grant-nonce reservation

Date: 2026-10-12
Parent Canonical Draft: PR #1568, commit
033b5b4b3d8a2129a89f09140c3b71c4c9674502
Qualification state: DRAFT / DEFAULT OFF / PRODUCT HOLD.

## Scope and prior evidence

The earlier Phase4L actual IB PAPER EUR/USD two-event native
test Ledger/Witness remains byte-unchanged and NOT production
qualified. It never had a genuinely independent root-approved
preappend Escrow. The original market outcome was 5-minute
midprice price-bps, NOT economic broker fill and after-cost PnL.

This branch does not retroactively sign or alter that market source.
All new Events and Root/Grant signers in its native tests are
SYNTHETIC TEST fixtures. There is no new broker order,
LLM inference, registered production root, or model promotion.

It closes two code verification gaps from the parent Draft:
1. The only unwitnessed original Ledger event can be an
   AuthenticatedOutcomeV2 after an authenticated DecisionV2.
2. A root-signed grant nonce previously lacked any separate
   durable owner-held replay guard.

## Feature-gated implementation (NOT enabled in production)

Feature: qualification-ack-only-recovery (DEFAULT OFF).

New ack_only_nonce.rs defines AckOnlyGrantNonceJournalV1.
The caller must provide a STABLE, PREEXISTING, owner-controlled
mode-0700 directory, not a path chosen by the signed grant.
Opening a swapped symlink is refused. Prior to each reservation,
the opened directory inode, device, UID and private mode must
still agree with the original path. The nonce maps to exactly
one owner-held deterministic filename, created O_EXCL, mode 0600
from birth, then fsynced and followed by directory fsync.

After original root/delegation/revocation-cut, source-time Escrow,
current RecoveryGrant and exact durable Ledger event validation
but BEFORE WitnessStore.advance, the native qualification entry
must fsync this one-use nonce reservation.

No reservation => NO Witness mutation. Process death after
reservation => an INDETERMINATE/HOLD state; the file must not be
silently deleted or reused on a retry. Existing fully ACKed
history requires no new event and rejects duplicate authorization.
No Ledger.append method is called by this feature.

The root-controlled native entrypoint now REQUIRES the nonce
journal argument; the old no-nonce public qualification entrypoint
is not retained. The returned test receipt reports its reserved
nonce digest only after the original Witness ACK succeeds.

The nonce store is NOT globally authoritative across hosts
unless a separate product Owner pins it for all recovery workers.
Directory rebind checking is not an atomic openat2 / physical
mount-namespace attestation. The code cannot establish
independent HSM custody, product Root enrollment, or a trusted
monotonic time by itself. Production remains HOLD.

## Executed native tests

Original Canonical typed synthetic DecisionV2 is durably
committed and witnessed at sequence 1; a synthetic terminal
OutcomeV2 is durably appended at sequence 2 without Witness.
Root/cut/Escrow/Grant typed test certificates must bind both
controllers, original objective and event identity, current cut,
exact previous and target chain anchors and signature.
The candidate reserves its nonce and advances Witness ONLY 1->2;
the original two Ledger record bytes remain identical.

The suite tests:
- Exact native Outcome ACK, no new Ledger event, duplicate grant
  cannot advance Witness twice.
- A DIFFERENT RUST TEST PROCESS independently recovers the same
  synthetic original Decision/Outcome after record append in both
  witness-lagged and fully ACKed states. Neither readback changes
  the original file bytes. This is process recovery, not a powercut.
- Another process fsyncs an original signed test nonce then
  deliberately exits code 47 before Witness advance. The
  owner process reopens the stable nonce store and refuses any
  automatic retry: the nonce is indeterminate but already used.
  This is controlled process termination, NOT sudden SSD power loss.
- Two concurrent thread reservations for the same nonce in the
  same owner-held directory: exactly one reservation succeeds.
  Different open file handles and cloned signed grants cannot reuse.
- Missing Escrow, revoked Root cut, expired grant, changed
  original objective/record/chain, counterfeit Root, same
  signer/controller, old Legacy event, two unwitnessed records,
  bad permissions, symlink or replaced nonce directory are
  rejected before Witness change.
- Source no-Git/Cargo modification outside this isolated
  qualification worktree. Default original native library
  serialization/signing tags are unchanged.

## Unclosed production gates

- Actual independent, root-approved Mac/X230 source-time Escrow,
  physical receipt durability, independent RecoveryAuthority
  administrators and external product root ceremony.
- Secure monotonic wall time, latest ROOT revocation/epoch,
  globally one-time durable nonce ownership/writer fencing and
  actual physical power-interruption qualification.
- Original opaque LLM full action candidate support and sampled
  per-state propensity, true broker fills and cost-complete net PnL,
  market-eligible SnapshotV3, Artifact Owner/CURRENT and
  independent unseen future trading efficacy.

Original test-only Market Ledger/Witness must not be relabelled
production source simply because the synthetic feature works.
Keep feature DEFAULT OFF, PR Draft, production product HOLD.

## Reproducible testing

Run the original pinned Cargo workspace with --offline --locked,
the original codex-hepta-learning-ledger and
codex-hepta-learning-artifacts packages, first with default
features and then with qualification-ack-only-recovery.
Also run Cargo Clippy --all-targets -- -D warnings, cargo fmt
--check. Exact logs and a create-only qualification receipt
are retained under the private Pocket4 operator evidence root
canonical-ackonly-outcome-20261012.

## Final Phase 4P native qualification evidence

Executed on Pocket4 against pinned original Cargo.lock SHA256:
8354b4cbdf14389db7aa5508e2ed5b524fc2d4c4ea0ecb475955c933f8bea389

- Default production Cargo (feature OFF): original learning-ledger
  118 passed, artifacts 92 passed, two original ignored, zero
  failures: 210 passed total.
- Qualification feature ON: learning-ledger 150 passed, artifacts
  92 passed, two original ignored, zero failures: 242 passed total.
  The focused ACK-only suite contains 32 tests including child-only
  test-process entrypoints; all 32 passed, zero failed.
- Clippy all-targets with -D warnings passed, cargo fmt --check
  passed, no modification of original Canonical source checkout.
- Full real Phase4L source-test original native Ledger and
  independent Witness hashes preserved byte-for-byte.
- No process-level test or synthetic grant promotes the actual
  prior market Ledger: there was no independent source-time Escrow.
- Initial private evidence *test log directory* was accidentally
  mode 0775 with log files mode 0664, due the host's inherited
  umask. This was detected and corrected to 0700/0600 before
  final qualification. It must NOT be claimed private-from-birth;
  new nonce files themselves were created mode0600 via O_EXCL.

The full originally executed two-suite Rust test logs, Clippy and
format logs, and final create-only fsynced receipt are privately
stored on Pocket4 at:

~/.local/state/heptatrader/operator-evidence/canonical-ackonly-outcome-20261012/

Final qualifier:
ackonly-V2-outcome-durable-nonce-final-qualification-v1.json

SHA256:
26a0917a1742fbfef1d395a17c06d0e76077736693f281a49b0fe646f38b5e23

RELEASE: HOLD_INDEPENDENT_PRODUCT_ROOT_PREAPPEND_ESCROW_TRUSTED_CLOCK_GLOBAL_NONCE_POWERLOSS_ORIGINAL_ACTION_POLICY_PNL

Do not enable this qualification feature in a deployed trading or
learning service, and do not merge based on tests alone.

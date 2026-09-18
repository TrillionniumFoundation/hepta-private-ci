# Durable causal episode ledger

This is the file-backed persistence sub-slice of `LRN-1-DURABLE-EPISODE-LEDGER`.
It uses the existing `LearningLedger` semantics and event/chain digests, not a
second causal ledger or a canonical platform wire protocol. It does not complete
all of LRN-1 or grant production activation.

## API and ownership

`DurableLedger::create(file, binding, max_records)` initializes an empty file;
`recover(file, binding, max_records, recovery)` never initializes missing history.
The host must pass a separately opened, already authorized read/write `File` and
an authenticated store/scope/purpose/epoch binding. No path, credential, socket,
provider, model handle or external fact writer is accepted by the adapter.
Cooperating independent writers are fenced using the standard exclusive file
lock. Locks are not a defense against hostile writers, aliases or privileged
filesystem modification. The host owns new-file directory synchronization,
revocation, isolation, encryption and filesystem qualification.

## Commit and recovery algorithm

The pure core now separates validation/preparation from publication. The public
in-memory `append` retains its behavior. The durable adapter prepares without
mutating the core, checks the exact predecessor, encodes one bounded event frame,
appends it, calls `sync_all`, and only then publishes the event and receipt in
memory. Failed semantic validation cannot write the file. I/O uncertainty poisons
the handle and blocks further reads/writes until reopen and reconciliation.
An equal canonical retry returns the original event/chain identity with the
existing `IdempotentReplay` disposition and performs no new disk write, including
a retry after later events. Candidate permutation remains canonical; changed
content under the same identity or a wrong predecessor is not last-write-wins.

A 72-byte HEPTLR01 header binds format version, host binding and checksum. Frames
use a checked length/complement pair, sequence, predecessor digest, the existing
canonical event encoding, chain digest and checksum. Numbers are big-endian.
Recovery bounds lengths before allocation, decodes typed events, runs the SAME
causal validation and reconstructs each exact canonical frame. Duplicate frames,
unknown types, noncanonical order, bad checksums and rehashed invalid lineage
reject. Only an incomplete final frame may be repaired.

`LedgerRecovery::Acknowledged(LedgerAnchor)` requires an externally retained
sequence and chain digest. Its prefix must exist and match before any repair.
Later valid complete frames are preserved for lost-acknowledgement reconciliation;
corruption after the anchor still rejects. Recovered bytes are synced before
exposing committed results. The host must authenticate and bind the witness,
retain it independently and acknowledge externally only after retaining it.
It must not retry a failed anchored recovery as `Unacknowledged`. The raw
`DurableLedger` deliberately does not own its acknowledgement witness, but the
product-facing `LedgerWriter` now composes it with a separately locked
`LedgerWitnessStore`. The writer syncs the ledger frame first and then advances
the independent HEPTLW01 witness before acknowledging success. A witness failure
after ledger sync is returned as indeterminate and reconciled from the original
identity; it is never converted into success. An unanchored recovery still
cannot detect loss of a whole valid suffix.

## Causal and resource boundaries

The existing explicit-abstain, complete-candidate, nonzero-propensity,
independent-observer-ID, terminal-outcome credit and no-double-credit rules are
preserved. Host authentication is still necessary: differing supplied identity
strings alone do not prove independent observation. Decisions, outcomes, credits
and logical revocations share one ordered durable chain. Replay applies all
revocations before exposing active records, including causal descendant exclusion.
Revoked bytes remain in the audit journal: this is NOT physical erasure, backup
deletion, machine unlearning or evidence of future learning improvement.

The original V1 file profile caps are 1..8192 records, 8 MiB per file, 32 KiB per encoded event,
128 candidates and 128 bytes per stable identity. Quota exhaustion stops rather
than dropping history. Replay and indexes are bounded by these caps; equal retry
lookup is linear in the bounded record count. The synced path has no hard
real-time or target-host latency claim. The V2 rotation and evaluated-shadow
consumer below do not add compaction, arbitrary owner migration, independent
witness storage or production enrollment.

## Production authenticated admission

The stable storage backends remain generic enough to replay V1 history, but the
product-facing admission surface is `LedgerWriter`. Its owned backend handle is
not exposed while the writer is in use. Product methods accept only typed,
signed V2 facts:

- `append_decision` requires a generator signature and exact candidate
  completeness with zero omitted candidates;
- `append_outcome` requires an independently controlled observer and enforces
  one linear correction head;
- `append_credit_batch` commits all allocations and residual in one frame after
  exact terminal-outcome conservation;
- `append_unlearning` records authenticated source→dataset→artifact invalidation;
- `freeze_dataset` derives active source rows and correction/revocation cuts
  from the current canonical ledger rather than accepting caller-supplied cuts.

The writer's trust state is an `ActivatedLearningTrustV1` created from a
generation-bound `LearningTrustDistributionV1`. Trust rotation is monotonic in
distribution generation/effective time and may not roll authority epoch back.
The host still owns distribution transport, current-key custody and revocation
publication.

`LedgerIndexCheckpointV1` is a rebuildable, content-addressed read accelerator.
It binds the exact anchor, record index, active projection, current correction
heads and revocation/unlearning frontier. Verification rebuilds it from the
ledger. It is discarded on mismatch and never replaces canonical replay.

## Verification and rollback

The existing eight core tests remain unchanged. Sixteen new tests cover actual
file recovery, all four event types, revocation descendants, acknowledged-history
loss at each final-frame cut, canonical retry after later events, stale CAS,
corruption, malformed lengths and variants, quota, writer fencing, failed writes,
unacknowledged complete frames, and an independent byte-level golden vector.
The one-event golden file is 362 bytes with SHA256
`eba8162e7d3f4e8eb26babe2552731774ee9c6cd04facf81a3bb2a004eefbfcf`.
Native filesystem and physical power-loss qualification are not implied by a
Linux test result. The dedicated read-only CI checks exact source and actual-base
synthetic merge independently. No parent work-package or capability status is
advanced by creating this code. Rollback leaves the new file inert; never read
an older snapshot as if it included later revocations or confirmed results.

## Normal owner-drop lock lifetime

Normal destruction explicitly unlocks the owned file before closing its handle.
On Linux a temporarily duplicated or inherited open description can otherwise
retain the lock after the owner closes, including during concurrent process
creation. A regression retains such a duplicate, proves another writer is
blocked while the owner lives, drops the owner, and verifies immediate recovery
without discarding the duplicate first. Dropping the old duplicate must not
release a newly acquired independent writer lock.

The duplicate exists only inside the regression fixture. No public handle is
exposed, and the host prohibition on shared writers or independently closing
inherited handles is unchanged. Unlock during Drop is best effort; errors are
not represented as successful commits, and normal file closure remains the
fallback. Existing commit synchronization and poison/recovery behavior remain
unchanged. Process death still requires OS handle closure and does not run Drop;
this is not a physical power-loss or hostile-writer guarantee.

## Segmented V2 persistence and production writer

`DurableLearningJournal` remains sealed to the actual `DurableLedger` and
`SegmentedLedger` implementations as a V1 compatibility/testing port. New
composed callers do not receive that raw port. The evaluated-shadow source
consumer now owns a `LedgerWriter`, which consumes the backend together with an
activated trust distribution and independent witness and writes authenticated
V2 decisions only. There is no second data owner.

`SegmentedLedger::create(owner_lock, first_segment, binding, limits)` takes only
host-authorized independent handles. A stable, exclusive owner lock spans all
rotations. Each segment also has a lock; sealed historical segments can be
inspected with a shared lock while a successor writer remains active.
`append` preserves the original global sequence, hash chain, causal indexes and
idempotency across segments. Outcomes and revocations in later segments continue
to refer to the original decisions; capacity never resets history.

The 136-byte `HEPTLS02` header binds owner scope, segment index, predecessor
sequence/digest, per-segment limits and checksum. Existing event frames are
unchanged. An 80-byte seal binds the exact segment and terminal record.
All integers are big-endian. Checksums detect corruption, not authorization.

`rotate(empty_successor, expected_head)` validates the candidate file before
sealing the predecessor, durably seals the old segment, then initializes and
syncs the successor. Empty segments cannot be sealed or rotated. A failed
successor initialization never re-enables the predecessor. I/O uncertainty
poisons the handle and requires recovery, not blind retry or overwriting files.

The host must create and authorize the stable lock and segment directory,
publish segment names with directory synchronization, retain the ordered series,
and independently authenticate/persist `LedgerSegmentCheckpoint` before
acknowledging that frontier externally. The checkpoint includes segment number,
record anchor and seal state. A record-only anchor cannot detect removal of an
acknowledged seal or an empty successor. `LedgerWriter::rotate_segment` now
advances the independent witness to the new segment topology before reporting
rotation success. The checkpoint and witness are minimum durability frontiers,
**not** materialized replay checkpoints or backups. Never recreate missing
acknowledged history or discard a failed witness.

`recover` validates the complete ordered series under the owner lock. Intermediate
segments must be sealed. Only an incomplete final tail may be repaired, and only
after the external minimum checkpoint has been validated. A sealed last segment
can be rotated after recovery but cannot receive new events. Completed frames
after a lost acknowledgement survive and reconcile with the same operation ID.

`inspect_ledger_segments` accepts a fully sealed history and an exact external
record anchor; a later anchor rejects an incomplete prefix. The result is a
historical snapshot. Readers and artifact consumers must still check current
revocation before final use. Revocation excludes causal descendants; it does not
physically erase old segment bytes or authorize restoring a revoked artifact.

The V1 codec remains unchanged and rejects V2 files. Existing V1 callers still
coerce to the durable port. There is no automatic in-place V1 migration or claim
that an old binary can read V2. Code rollback must use a compatible backend and
preserve all acknowledged history, not substitute an older data snapshot.

Per-segment bounds remain 1..8192 records and 4096 bytes..8 MiB. The series has
at most 1024 segments and retains the pure core's existing one-million-record
limit. Recovery and in-memory indexes still grow with retained history. This
implements rotation and cross-segment continuity, not unlimited storage,
constant-time recovery, compaction, physical erasure or sustained throughput.

The normal owner test inventory includes 8,200 records over 257 bounded segments,
cross-segment outcomes/revocations/retries, shared historical reads, reordered or
corrupt series, lost seal/empty successor rejection, partial-tail repair and
actual child-process exit after seal or successor initialization. The existing
evaluated-shadow consumer is tested through rotation, reopen and old-run replay;
invalid signatures still reject before any host port or journal mutation.
Run the existing entrypoint, without an alternate workspace or lowered gates:

```sh
just test --locked -p codex-hepta-learning-ledger -p codex-hepta-intelligence
```

These are local filesystem and synthetic evaluation scenarios, not physical
power-loss, independent acceptance, production efficacy or hostile-writer proofs.

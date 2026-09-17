# Durable causal episode ledger

This is the file-backed persistence sub-slice of `LRN-1-DURABLE-EPISODE-LEDGER`.
It uses the existing `LearningLedger` semantics and event/chain digests, not a
second causal ledger or a canonical platform wire protocol. It does not grant
production activation, independent acceptance, promotion or release.

## API and ownership

`DurableLedger::create(file, binding, max_records)` initializes an empty V1 file;
`recover(file, binding, max_records, recovery)` never initializes missing history.
`SegmentedLedger` extends the same causal history across bounded sealed segments.
The host passes already authorized file capabilities; neither backend accepts an
ambient path, credential, socket, provider, model handle or external fact writer.

Raw durable backends are recovery/maintenance surfaces. Source-level consumers
that need to return acknowledged durable success should use
`WitnessedLearningLedger` through the sealed `AcknowledgedLearningJournal` port.
That wrapper couples the actual journal to a separately opened
`LedgerWitnessStore` and does not return a successful mutation until both the
journal and witness frontier have been synchronized.

Cooperating writers are fenced by exclusive file locks. Locks are not a defense
against hostile aliases, privileged filesystem modification or an administrator
that controls every copy of the data. The host still owns trusted file opening,
new-file and parent-directory synchronization, encryption, ACLs, backup policy,
filesystem qualification and the operational separation that makes the witness
independent from the protected journal.

## Single-event commit and recovery

The pure core separates validation/preparation from publication. A durable
single append prepares without mutating the core, checks the exact predecessor,
encodes one bounded canonical frame, appends it, calls `sync_all`, and only then
publishes the event and receipt in memory. Failed semantic validation writes no
bytes. I/O uncertainty poisons the handle and requires reopen/reconciliation.

An equal canonical retry returns the original event/chain identity with
`IdempotentReplay` and writes no duplicate frame, including a retry after later
events. Changed content under an existing identity or a wrong predecessor
conflicts rather than using last-write-wins semantics.

A 72-byte `HEPTLR01` header binds format version, host binding and checksum.
Frames use a checked length/complement pair, sequence, predecessor digest,
canonical V1 event encoding, chain digest and checksum. Numbers are big-endian.
Recovery bounds lengths before allocation, decodes typed events, runs the same
causal validation, and reconstructs each exact canonical frame. Duplicate
frames, unknown types, noncanonical order, bad checksums and rehashed invalid
lineage reject. Only an incomplete final frame may be repaired.

`LedgerRecovery::Acknowledged(LedgerAnchor)` validates an externally retained
minimum sequence and chain digest before repair. A valid complete suffix after
that anchor is preserved for lost-acknowledgement reconciliation; corruption
after the anchor still rejects. A failed acknowledged recovery must never be
retried as `Unacknowledged` merely to make the store open.

## Independent acknowledgement witness

`LedgerWitnessStore` is the native append-only witness implementation for a
record-level acknowledgement frontier. The host supplies a separately opened,
authorized file capability and a non-zero witness binding. The witness does not
read or derive its own state from the protected journal.

The witness uses a checksum-bound `HEPTLW01` header followed by fixed-size
monotonic transition frames. Each transition binds the exact previous and next
`LedgerAnchor`. Reusing a stale predecessor, moving backwards, changing a digest
at the same logical frontier, corrupting a complete frame or exceeding the
bounded witness history fails closed. Only an incomplete final witness frame may
be truncated during recovery. `advance` returns only after the new frame is
`sync_all`-durable; I/O uncertainty poisons the handle.

`WitnessedLearningLedger::attach` checks the relationship between recovered
journal and recovered witness before exposing a consumer:

- empty journal plus empty witness is valid;
- a non-empty journal cannot be promoted from an empty witness;
- a non-empty witness must match an exact journal prefix;
- a longer valid complete journal suffix may be reconciled as lost
  acknowledgement by durably advancing the witness before the consumer is
  exposed;
- a witness ahead of the journal or a digest mismatch fails closed.

A separate file capability is necessary but is not itself proof of an
independent failure domain. Production qualification still has to prove that
ledger and witness cannot be rolled back together by the same ordinary restore,
credential, directory or administrative path.

## Atomic ordered batches

Both `DurableLedger` and `SegmentedLedger` expose `append_batch` for semantic
publication units that must not be acknowledged one row at a time. The complete
ordered batch is first prepared against a cloned `LearningLedger`; predecessor
continuity, every causal invariant and capacity are validated before writing.
All new frames are then written contiguously and synchronized once. Only after
successful synchronization is the staged core published in memory.

An exact replay prefix followed by a missing suffix is supported for recovery
from an indeterminate completed write. Replay after a newly staged event is a
conflict. A batch that cannot fit the configured V1 file or current V2 segment,
including the reserved segment seal, fails before any new frame is written.
Segment rotation is never performed implicitly in the middle of a batch.

`WitnessedLearningLedger::append_batch` advances the independent witness from the
pre-batch head to the terminal batch head before returning any successful batch
receipt.

## Conserved causal credit

The compatibility ledger still stores individual `CreditAssignment` events, but
`append_conserved_credit_batch_v1` binds the V2 conservation unit to durable
history. It obtains the current acknowledged snapshot, replays it through the
same causal core, derives the active terminal outcome value for the submitted
episode/outcome identity, rejects a submitted terminal value that differs from
the ledger, applies `finalize_credit_batch`, derives deterministic per-target V1
record/credit identities, and commits every allocation through one witnessed
atomic batch.

Each compatibility credit event binds the V2 batch digest as its support digest.
Thus a successful source-level conserved-credit commit means conservation was
checked against actual active terminal ledger state and the complete allocation
set reached both the journal and its witness frontier. It does not make the
allocator scientifically independent or grant selection/promotion authority.

## Ledger-derived dataset freeze

`DatasetSnapshotV2` and `freeze_dataset` remain source-compatible surfaces for an
already prepared V2 request. `DatasetSnapshotReceiptV3` adds independently
recomputable semantic fields so consumers can verify its dataset digest.

For composition where membership must not be caller asserted,
`freeze_dataset_from_ledger_v3` accepts a replay-validated `LedgerSnapshot` plus
a bounded plan. It derives the actual ledger head, eligible logical frontier,
active objective-related decision/outcome/credit membership, relevant logical
revocation cut and active intermediate-outcome count. The caller cannot replace
the source-record digest set, head or revocation cut on this strict path.

The V1 event format has no censored-outcome state and does not contain sufficient
wall-clock observation evidence to derive an outcome-time watermark. The strict
V1-compatible freeze therefore never invents censored counts; authenticated V2
outcome evidence and the product host remain responsible for full delayed and
censored semantics.

## Causal and resource boundaries

Explicit abstention, complete candidate sets, non-zero chosen propensity,
independent-observer rules, terminal-outcome credit, no-double-credit and
append-only logical revocation remain enforced at their declared layers. Signed
V2 evidence can be admitted through `LearningEvidenceVerifierV1`; differing
identity strings alone are not authentication or organizational independence.

Decisions, outcomes, credits and logical revocations share one ordered durable
chain. Replay applies revocations before exposing active records, including
causal descendant exclusion. Revoked bytes remain in the audit journal. This is
**not** physical erasure, backup deletion, already-distributed artifact deletion,
model-weight unlearning or evidence of future learning improvement.

The original V1 file profile caps remain 1..8192 records, 8 MiB per file,
32 KiB per encoded event, 128 candidates and 128 bytes per stable identity.
Quota exhaustion fails rather than dropping history. Replay and indexes remain
bounded by configured retained history; the synced path makes no hard real-time
or target-host latency claim.

## Verification and rollback

Owner tests cover canonical file recovery, all V1 event kinds, causal revocation,
acknowledged-history loss, partial-tail repair, idempotent replay after later
events, stale CAS, corruption/malformed frames, quota, writer fencing, failed
writes, byte-level golden compatibility, segment rotation and cross-segment
lineage.

Additional closure tests cover witness monotonicity and recovery, refusal to
promote non-empty unwitnessed history, witnessed lost-ack reconciliation,
witnessed atomic-batch terminal heads, durable conserved-credit publication and
ledger-derived dataset membership.

Native Linux filesystem tests do not imply physical power-loss qualification.
The dedicated CI runs exact source and, for pull requests, an ordered-parent
synthetic merge. A source test or CI pass does not advance production activation
or external capability claims by itself.

Code rollback must use a binary/backend compatible with every acknowledged
format and preserve the current minimum witness/revocation frontier. Never
substitute an older data snapshot as if it contained later revocations or
confirmed outcomes.

## Normal owner-drop lock lifetime

Normal destruction explicitly unlocks the owned file before closing its handle.
On Linux a temporarily duplicated or inherited open description can otherwise
retain the lock after the owner closes, including during concurrent process
creation. Regression coverage retains such a duplicate, proves another writer
is blocked while the owner lives, drops the owner, and verifies immediate
recovery without discarding the duplicate first. Dropping the old duplicate
must not release a newly acquired independent writer lock.

Unlock during `Drop` is best effort; errors are not represented as successful
commits and normal file closure remains the fallback. Process death requires OS
handle closure and does not run `Drop`; this is not a physical power-loss or
hostile-writer guarantee.

## Segmented V2 persistence

`DurableLearningJournal` is sealed to the actual `DurableLedger` and
`SegmentedLedger` implementations. `AcknowledgedLearningJournal` is separately
sealed to the witnessed wrapper, preventing arbitrary fixtures from presenting
themselves as acknowledged product persistence.

`SegmentedLedger::create(owner_lock, first_segment, binding, limits)` takes only
host-authorized handles. A stable exclusive owner lock spans rotations. Each
segment has its own lock; sealed historical segments can be inspected under a
shared lock while a successor writer remains active. Sequence, hash chain,
causal indexes and idempotency remain global across segments.

The 136-byte `HEPTLS02` header binds owner scope, segment index, predecessor
sequence/digest, per-segment limits and checksum. Existing event frames are
unchanged. An 80-byte seal binds the exact segment and terminal record. Checksums
detect corruption, not authorization.

`rotate(empty_successor, expected_head)` validates the candidate file before
sealing the predecessor, durably seals the old segment, then initializes and
syncs the successor. Empty segments cannot be sealed or rotated. A failed
successor initialization never re-enables the predecessor. I/O uncertainty
requires recovery, not blind retry or overwrite.

The host must durably create/publish the stable owner lock and ordered segment
files. `LedgerSegmentCheckpoint` remains the minimum segment-level recovery
frontier because a record-only witness cannot prove that an acknowledged seal or
empty successor generation was retained. `LedgerWitnessStore` supplies the
native record-level acknowledgement witness; it does not replace the segment
checkpoint's seal/generation semantics.

Recovery validates the complete ordered series. Intermediate segments must be
sealed. Only an incomplete final tail may be repaired after the external minimum
checkpoint is validated. A sealed final segment can be rotated after recovery
but cannot receive new events. Completed frames after a lost acknowledgement
survive and reconcile with the same identities.

`inspect_ledger_segments` accepts a fully sealed history and exact external
record anchor. The result is a historical snapshot; readers and artifact
consumers must still check current revocation before final use.

The V1 codec remains unchanged and rejects V2 segment files. There is no
automatic in-place V1 migration and no claim that an old binary reads V2.
Per-segment limits remain 1..8192 records and 4096 bytes..8 MiB, at most 1024
segments, with the pure core's one-million-record bound. Recovery and in-memory
indexes still grow with retained history. Rotation implements bounded continuity,
not unlimited storage, constant-time recovery, compaction, physical erasure or
sustained-throughput qualification.

## Production evidence still required

The repository source now contains native record-level witness persistence,
witness-gated acknowledged commits, atomic durable batches, conserved-credit
commit binding and ledger-derived dataset freeze. It still cannot self-issue the
following deployment facts:

- identity of a live named production caller using the acknowledged port;
- current production trust-root/signer distribution and rotation authority;
- exclusive physical writer and independently administered ledger/witness paths;
- target-host directory/fsync, disk-full, process-crash, power-loss, restore,
  latency, throughput and storage-growth measurements;
- live independent outcome/future-calendar evidence;
- physical erasure, backup purge or model-weight unlearning receipts;
- independent semantic acceptance, canary, selection, promotion or release.

For source verification, run the repository-owned entrypoint without lowering
its gates:

```sh
just test --locked -p codex-hepta-learning-ledger -p codex-hepta-intelligence
```

These remain source/local-filesystem scenarios until exact-candidate CI and the
external product evidence gates are satisfied.

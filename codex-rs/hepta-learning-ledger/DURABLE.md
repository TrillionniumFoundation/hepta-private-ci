# Durable causal episode ledger

This is the file-backed persistence slice of `LRN-1-DURABLE-EPISODE-LEDGER`.
It uses one ordered `LearningLedger` hash chain for retained V1 events and additive
authenticated V2 facts. It is not a second platform wire protocol and it does not
by itself grant production activation, selection, promotion or release.

## API and ownership

`DurableLedger::create(file, binding, max_records)` initializes an explicitly
empty V1-compatible journal; `recover(file, binding, max_records, recovery)` never
initializes missing history. `SegmentedLedger` provides bounded rotation over the
same event frames and causal indexes.

The host passes separately opened, already authorized files plus an authenticated
store/scope/purpose/epoch binding. The adapters accept no ambient path,
credential, socket, provider, model handle or external fact writer. Cooperative
writers are fenced by exclusive file locks. Locks are not a defense against a
hostile privileged filesystem writer, aliases outside the host policy or rollback
of the whole storage domain. The product host owns path qualification, directory
synchronization, isolation, encryption, backup/restore and process enrollment.

## Commit and recovery algorithm

The pure core separates validation/preparation from publication. A durable append
prepares without mutating memory, checks the exact predecessor, encodes one
bounded frame, appends it, calls `sync_all`, and only then publishes the same
record to the in-memory causal indexes. Failed semantic validation cannot write
the file. I/O uncertainty poisons the handle and blocks further reads/writes
until reopen and reconciliation.

An equal canonical retry returns the original event/chain identity with
`IdempotentReplay` and performs no new disk write, including after later events.
Changed content under the same record identity conflicts; a wrong predecessor is
not last-write-wins.

The 72-byte `HEPTLR01` header binds format version, host binding and checksum.
Frames use a checked length/complement pair, logical sequence, predecessor chain
digest, canonical event bytes, chain digest and frame checksum. Recovery bounds
lengths before allocation, decodes typed records, re-runs the same causal
validation, reconstructs the canonical frame and rejects duplicates, unknown
types, noncanonical content, bad checksums and invalid lineage. Only an incomplete
final frame may be repaired.

`LedgerRecovery::Acknowledged(LedgerAnchor)` requires a separately retained
minimum acknowledged sequence and chain digest. Its prefix must exist and match
before repair. Later valid complete frames are retained for lost-acknowledgement
reconciliation; corruption after the anchor still rejects. A failed anchored
recovery must never be retried as `Unacknowledged`.

## Independent acknowledgement witness

The repository now supplies concrete witness mechanics through
`FileLearningWitnessStore` in `src/witness.rs`. The `HEPTLW01` journal is a
separate file capability with a 72-byte binding/checksum header and chained
104-byte acknowledgement frames. Each frame binds:

- the acknowledged ledger sequence;
- the acknowledged ledger chain digest;
- the prior witness-frame digest;
- a digest of the new witness-frame preimage.

Witness persistence is monotonic, allows exact idempotent replay, rejects gaps and
regressions, and repairs only an incomplete final unacknowledged frame. This
closes the repository-source gap where `LedgerAnchor` existed without a concrete
append-only witness implementation.

It does **not** prove administrative or physical independence. Production must
place the witness on a separately governed rollback/durability path. A ledger and
witness stored in the same snapshot domain can still be rolled back together and
must not be described as independent evidence.

`ProductionLearningLedger` requires the live journal head to equal the witness
frontier at construction. Its acknowledged write order is validation/signature
verification -> durable journal sync -> witness sync -> external receipt. If the
journal sync succeeds and witness persistence becomes uncertain, no success is
returned and a later mutation cannot step over the unwitnessed tail; recovery
must reconcile it.

## Additive authenticated V2 records

The canonical event domain is retained. Existing V1 tags and bytes are unchanged:

- `0` decision;
- `1` outcome;
- `2` legacy single credit assignment;
- `3` revocation.

Additive tags are:

- `4` `AuthenticatedDecisionRecordV2`;
- `5` `AuthenticatedOutcomeRecordV2`;
- `6` `ConservedCreditBatchRecordV2`.

The authenticated decision persists generator identity and generator-relative
candidate completeness. The authenticated outcome retains pending/censored/
terminal state plus correction predecessor. The conserved-credit event persists
the whole finalized allocation batch and its recomputable batch digest as one
atomic journal event. Replay rejects causal drift rather than trusting that the
record was valid merely because it was written once.

V1 records are never relabelled as V2. An old binary that does not understand the
new tags must not open a journal after authenticated V2 records have been
acknowledged. Code rollback must retain a binary/backend combination that can
interpret every acknowledged record.

## Causal and resource boundaries

The stable explicit-abstain, complete-candidate, nonzero-propensity,
independent-observer, terminal-outcome and no-double-credit rules remain. The
production V2 gate adds cryptographic evidence admission, controller separation,
delayed/censored outcome state, correction lineage and atomic credit
conservation. Differing strings alone are never treated as proof of independent
observation.

Decisions, outcomes, conserved credit and logical revocations share one ordered
chain. Replay applies revocations before exposing active records, including
causal descendant exclusion. Revoked bytes remain in the audit journal. This is
**not** physical erasure, backup deletion, removal from all derived artifacts or
model-weight unlearning.

The retained V1 single-file profile is 1..8192 records, at most 8 MiB per file,
at most 32 KiB per encoded event, at most 128 candidates and at most 128 bytes per
stable identity. The pure core remains capped at one million records. V2 atomic
credit batches are additionally capped at 224 allocations so a complete batch
fits the existing frame limit. Quota exhaustion fails closed rather than dropping
history.

Replay and in-memory indexes remain proportional to retained history. The module
has no constant-time recovery, general compaction or hard real-time latency claim.
Those remain scale/host qualification work rather than being hidden behind a
larger limit.

## Verification and rollback

The retained durable tests cover file recovery, the V1 event set, revocation
descendants, acknowledged-history loss, exact retry, stale CAS, corruption,
malformed lengths/variants, quota, writer fencing, failed writes, unacknowledged
complete frames and byte-level golden compatibility. The original one-event V1
golden file remains 362 bytes with SHA256
`eba8162e7d3f4e8eb26babe2552731774ee9c6cd04facf81a3bb2a004eefbfcf`.

New focused tests cover:

- witness append/idempotency/recovery and partial-tail repair;
- authenticated file-backed decision/outcome/credit publication;
- conserved credit rejection without ledger/witness advancement;
- correction supersession in ledger-derived dataset membership;
- exact ledger/witness frontier matching.

A Linux CI pass does not imply physical power-loss qualification. No source test
may be converted into a claim about a deployed writer, independent observer or
longitudinal learning efficacy.

## Normal owner-drop lock lifetime

Normal destruction explicitly unlocks the owned file before closing its handle.
On Linux, a duplicated or inherited open description can otherwise retain a lock
after the logical owner closes. Regression coverage retains such a duplicate,
proves a contender is blocked while the owner lives, drops the owner and verifies
recovery without first discarding the duplicate. Dropping the old duplicate must
not release a newly acquired independent writer lock.

The duplicate is only a test fixture. Public handles are not exposed. Unlock in
`Drop` is best effort; commit durability never depends on it. Process death relies
on OS handle closure and does not execute `Drop`; this is not a physical
power-loss or hostile-writer guarantee.

## Segmented persistence

`DurableLearningJournal` is sealed to the actual `DurableLedger` and
`SegmentedLedger` implementations. Qualification fixtures cannot implement a fake
durable journal. The port exposes append plus an immutable snapshot used by the
authenticated production gate.

`SegmentedLedger::create(owner_lock, first_segment, binding, limits)` takes only
host-authorized independent handles. One stable exclusive owner lock spans all
rotations. Each segment has a lock; sealed historical segments may be inspected
with a shared lock while a successor writer remains active. Global sequence,
hash chain, causal indexes and idempotency continue across segments.

The 136-byte `HEPTLS02` header binds owner scope, segment index, predecessor
sequence/digest, per-segment limits and checksum. Event frames are the same
frames used by the single-file journal. An 80-byte seal binds the exact segment
and terminal record. Checksums detect corruption, not authorization.

`rotate(empty_successor, expected_head)` validates the host-created successor,
durably seals the predecessor and only then initializes/syncs the new segment.
Empty segments cannot be sealed or rotated. Uncertain I/O poisons the handle and
requires recovery; the old sealed segment is never silently made appendable
again.

The host must durably publish segment names, retain the ordered series and
independently persist `LedgerSegmentCheckpoint` when segment/seal identity is part
of the acknowledged frontier. A record-only anchor does not prove that a seal or
empty successor still exists. The record witness and segment checkpoint therefore
serve related but distinct rollback boundaries.

Recovery validates the complete ordered series under the owner lock. Intermediate
segments must be sealed. Only an incomplete final tail may be repaired after the
external minimum checkpoint is validated. A sealed final segment can be rotated
after recovery but cannot receive new events.

`inspect_ledger_segments` accepts a fully sealed history and an exact external
record anchor. A later current anchor rejects an incomplete prefix. Inspection is
a historical snapshot; consumers must still check current revocation before final
use.

Per-segment bounds remain 1..8192 records and 4096 bytes..8 MiB, with at most
1024 segments and the pure core's one-million-record retained-history limit.
Rotation is capacity management, not compaction or proof of sustained production
throughput.

## Production composition and remaining evidence

See [`PRODUCTION.md`](PRODUCTION.md) for the complete authenticated commit order,
signing domains, ledger-derived freeze policy and trust boundary.

Repository source now contains the production composition **mechanics**. The
following facts still require external/deployment evidence and remain fail-closed:

- the named product process/callsite actually using the gate;
- exclusive physical writer and durable-directory ownership;
- current production signer/trust-root distribution;
- witness placement outside the common rollback domain;
- live independent outcomes;
- target-host process-kill, physical power-loss, latency, storage and throughput
  measurements;
- physical erasure/model-unlearning/non-resurrection evidence;
- independent acceptance, canary, promotion and release.

Run the normal owner and relevant consumer tests without lowering gates:

```sh
just test --locked -p codex-hepta-learning-ledger -p codex-hepta-intelligence
```

The dedicated Lane E workflow additionally checks all-target compilation, strict
Clippy/rustfmt, cross-crate causal closure and an ordered-parent synthetic merge.

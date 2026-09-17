# Authenticated production composition boundary

`ProductionLearningLedger` is the repository-owned composition gate that joins
causal V2 admission, the existing append-only durable journal, and a separately
retained acknowledgement witness. It removes the previous source-level gap where
V2 correctness checks could be called independently from the durable V1 writer.
It does **not** by itself establish that any deployed product process is the
exclusive physical writer or that external qualification has passed.

## Commit order and acknowledgement rule

Every acknowledged mutation follows one order:

1. verify current signed evidence against the host-supplied immutable
   `LearningEvidenceVerifierV1` trust snapshot;
2. validate candidate, outcome, role-separation, lineage or credit invariants;
3. require the caller's expected predecessor to equal the independently retained
   witnessed frontier;
4. append the typed event to `DurableLedger` or `SegmentedLedger` and complete its
   `sync_all` durability point;
5. persist the new `LedgerAnchor` to the independent witness and sync it;
6. only then return `ProductionCommitReceiptV1` to the caller.

A durable append followed by witness failure is intentionally not acknowledged.
The next mutation cannot step over that tail because the production gate requires
its predecessor to equal the witness frontier. Reopen/reconciliation must retain
the durable suffix and advance the authenticated witness; it must not rewrite or
discard the committed ledger event.

`ProductionLearningLedger::new` refuses to start when the journal head and
witness frontier differ. Product recovery therefore has to reconcile an
unacknowledged durable tail before admitting new mutations.

## Durable V2 event compatibility

The stable event domain and the existing V1 tags remain unchanged:

- `0`: decision;
- `1`: outcome;
- `2`: single legacy credit;
- `3`: revocation.

Additive V2 tags are:

- `4`: authenticated decision;
- `5`: authenticated delayed/censored/corrected outcome;
- `6`: conserved credit batch.

Replay decodes those records and runs the same causal checks again. Old records
are never automatically relabelled as V2. Older binaries that do not understand
new tags must not be used to open a journal after V2 records have been admitted.
Rollback therefore requires a binary/backend pair compatible with every
acknowledged record.

## Authenticated decision and outcome admission

A production decision binds the generator signature to the exact record,
episode, objective, policy, canonical candidate IDs, selected action,
propensity, generator-relative completeness digest and expected durable
predecessor. `CandidateSetCompletenessReceiptV1.generator_id` must match the
verified generator principal.

A production outcome binds the observer signature to the complete
`AuthenticatedOutcomeV1` plus the expected predecessor. It requires a durable
V2 decision for the episode, verifies signed generator/observer separation by
principal, credential chain, signing key and controller, and then applies the
V2 pending/censored/terminal and correction rules. Missing outcomes never become
zero reward.

## Atomic conserved credit

The production path does not publish V2 causal credit as independent V1
`CreditAssignment` rows. It verifies an evaluator-signed
`CreditAllocationBatchV1`, requires an authenticated decision and terminal
outcome, checks allocator/generator separation, verifies that the durable terminal
outcome exactly equals the batch total, and writes the complete allocation set as
one `ConservedCreditBatchRecordV2`.

The durable profile caps one batch at 224 allocations so the event remains within
the existing 32 KiB frame limit. Larger causal credit plans must be rejected or
replanned; they must not be split into partially acknowledged batches.

## Ledger-derived dataset freeze

`ProductionLearningLedger::freeze_dataset` does not accept caller-supplied source
record digests, correction cuts, revocation cuts or pending/censored counts.
Instead it:

- requires the live journal head to equal the witness frontier;
- binds an exact caller-signed eligible frontier and prefix head;
- replays the exact prefix through `LearningLedger::from_snapshot`;
- derives active records for the requested objective;
- excludes revoked causal descendants;
- treats a corrected authenticated outcome as superseding its named predecessor;
- derives correction and revocation cut digests from the prefix;
- derives pending and censored counts;
- feeds those derived values into `DatasetSnapshotReceiptV3` verification.

This closes the repository-side membership/provenance gap. It does not prove that
a real external outcome is scientifically correct or that an external data owner
consented to its use.

## Witness format and independence boundary

`FileLearningWitnessStore` provides a concrete append-only `HEPTLW01` witness
journal. Its 72-byte header binds the host-provided witness identity. Each
104-byte frame stores the acknowledged ledger sequence and chain digest, the
previous witness digest, and a digest of the new frame preimage. Recovery rejects
binding drift, sequence gaps, regressions and edited/reordered complete frames;
only an incomplete final unacknowledged frame is trimmed.

Repository source can prove these mechanics. It cannot self-prove administrative
or physical independence. A production deployment must place the witness on a
durability/authority path that cannot be rolled back together with the ledger,
and its product receipt must name that store, its controller, backup policy and
recovery generation.

## Trust lifecycle

`LearningEvidenceVerifierV1` consumes host-owned trust state and already enforces
scope, objective, epoch, validity window, signer role, revocation, payload digest,
Ed25519 signature and controller separation. `ProductionLearningLedger` owns an
immutable verifier generation: trust-root rotation or authority-epoch change
requires constructing a new service generation after recovery/reconciliation.

This source does not invent a production PKI, signer distribution service or
credential issuer. Those remain host responsibilities and external evidence
requirements.

## Directory and exclusive-writer obligations

The journal, owner lock, segment files and witness are supplied as already opened
file capabilities. The selected product host remains responsible for:

- trusted path resolution and parent-directory ownership;
- create/rename/directory `fsync` discipline;
- filesystem and encryption qualification;
- process identity and exclusive physical writer enrollment;
- placement of the witness outside the common rollback domain;
- backup/restore and disaster-recovery ordering;
- target-host latency, storage-growth, process-kill and power-loss evidence.

A source test caller, qualification harness or shadow caller is not evidence that
these duties are satisfied in production.

## Unlearning claim boundary

Revocation is append-only logical exclusion. Replay prevents revoked decisions
and their outcome/credit descendants from reappearing as active learning facts,
and ledger-derived dataset freezes exclude them. The audit bytes deliberately
remain in the journal.

Therefore this module does not claim physical erasure, backup destruction,
removal from every previously materialized artifact, or model-weight unlearning.
Those operations require their respective owners and independently verifiable
non-resurrection/erasure receipts.

## Qualification

Repository qualification must exercise the exact PR head and an ordered-parent
synthetic merge and includes the new file-backed production-path/witness tests.
Passing source CI proves source behavior only. The following remain separate
external gates until immutable receipts exist for the exact candidate:

- a named deployed product caller and exclusive physical writer;
- current signer/trust-root distribution in that host;
- administratively independent witness placement;
- real independent terminal outcomes and future-calendar evidence;
- target-host crash/power-loss/latency/throughput measurements;
- independent semantic acceptance;
- canary, selection, promotion and release decisions.

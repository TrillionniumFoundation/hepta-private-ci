# `learning.ledger` production closure

This document defines the repository-controlled production boundary for the
append-only causal ledger. It is intentionally narrower than activation or
release: repository code can make unsafe composition impossible or explicit,
but it cannot self-issue external trust, physical durability, long-term efficacy,
independent acceptance, canary, promotion or release evidence.

## Required production write sequence

A production caller must use the following order for every acknowledged learning
fact:

1. authenticate the current principal/evidence against the host-owned trust root;
2. validate the applicable causal invariant (candidate completeness, independent
   outcome, conserved credit, correction/revocation lineage);
3. bind the exact durable predecessor;
4. append to `DurableLedger` or `SegmentedLedger`;
5. sync the ledger bytes;
6. persist the resulting `LedgerAnchor` through `LedgerWitnessStore` on a
   separately governed file/storage capability;
7. sync the witness;
8. only then return success to the caller.

`WitnessedLearningJournal` implements steps 3-8 for the two sealed durable journal
implementations. A witness failure after ledger sync returns
`CommittedButUnwitnessed`; callers must retry the exact same operation identity,
predecessor and semantics. They must never mint a replacement event.

## Independent witness placement

`LedgerWitnessStore` is an implementation, not proof of organizational
independence. The product host must place its file on an independently protected
storage boundary from the ledger and bind both to the same authenticated
store/scope/purpose generation. Backing up ledger and witness in one rollbackable
snapshot does not qualify as independent retention.

The witness format is append-only and checksum chained. Equal retries are
idempotent; sequence gaps, same-sequence digest drift, malformed/truncated entries
and binding mismatches fail closed.

## Dataset freeze

Production dataset creation should use
`freeze_dataset_receipt_from_ledger_v3`, not caller-selected
`source_record_digests`. The function replays the authoritative
`LedgerSnapshot`, applies revocation lineage, limits membership to the declared
eligible frontier, excludes revocation control rows from training membership,
and derives the canonical source digest set and ledger head.

Downstream consumers should additionally call
`verify_dataset_snapshot_receipt_against_ledger_v3` when the authoritative
snapshot is available. This rejects stale heads, inserted rows, omitted active
rows and resurrection of revoked rows.

Pending/censored outcome counts and correction/revocation cut semantics remain
V2 policy metadata and must still be supplied by the authenticated product
composition. The ledger-bound membership API does not manufacture those facts.

## Trust-root lifecycle

`LearningEvidenceVerifierV1` verifies Ed25519 evidence against one immutable
host-owned `LearningEvidenceTrustV1` snapshot. Production integration remains
responsible for loading the current trust revision, rotating authority epochs,
distributing signer/controller mappings, and revoking stale keys before creating
the verifier. A submitted evidence object may never choose or replace the trust
snapshot.

## Physical erasure and model unlearning

Logical revocation is implemented and affects active ledger membership and
ledger-derived dataset freezes. It does not erase append-only audit bytes, purge
backups, delete external artifacts, or prove that a trained model has forgotten a
record. Those are separate external capabilities and evidence gates. No
repository status may relabel logical revocation as physical erasure or model
unlearning.

## External gates that remain outside repository self-certification

The following evidence must be issued by the responsible deployment or review
owner for the exact candidate:

- named production process and authenticated callsite;
- exclusive physical writer and durable directory ownership;
- independent placement/retention of the witness store;
- current production signer/trust-root distribution and revocation operation;
- live independent terminal outcomes;
- target-host crash, filesystem, latency, storage-growth and throughput evidence;
- backup/restore and physical-erasure evidence where claimed;
- independent semantic acceptance;
- canary, selection, promotion and release decisions.

Source tests, shadow callers and synthetic time fixtures do not satisfy these
external gates.

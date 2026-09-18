# kernel.evidence external anti-rollback and restore frontier V1

This document defines the production boundary required to turn the local SQLite
integrity checks into rollback-resistant operational evidence. It is a deployment
contract, not a claim that an external checkpoint service is already enrolled.

## Threat model

Local SQLite quick-checks, migration checksums, record digests, immutable triggers
and Ed25519 receipt signatures detect corruption and unauthorized record rewriting.
They cannot by themselves distinguish the newest valid database from an older,
internally valid backup. A complete replacement with an older signed database is
therefore a rollback unless an independently retained monotonic frontier rejects it.

## External checkpoint object

After each accepted backup generation, the operator persists an external checkpoint
outside the evidence database and outside the backup set being protected. The
checkpoint is append-only and contains:

- schema identifier `hepta.kernel-evidence.external-checkpoint.v1`;
- exact source commit and source tree of the writer binary;
- migration ledger digest and highest installed migration version;
- database file lineage name (`hepta_evidence_2.sqlite`);
- transactionally observed high-water sequence for every append-only evidence table;
- digest of the canonical high-water manifest;
- latest qualification evidence ID and record digest when present;
- current revocation/supersession frontier digest;
- backup generation ID and backup artifact digest;
- checkpoint predecessor digest;
- checkpoint observation time and expiry/retention policy revision;
- independent checkpoint signer principal, key reference and detached signature.

A checkpoint with a missing predecessor, lower high-water value, changed lineage,
invalid signature or a backup digest mismatch is rejected.

## Backup and restore procedure

1. Quiesce the writer or use a SQLite online backup transaction that produces one
   transactionally consistent database image. Never copy a live main/WAL pair
   independently.
2. Run `PRAGMA quick_check`, verify the exact migration ledger and open the copy
   through the read-only evidence store path.
3. Produce the canonical high-water manifest and external checkpoint. Persist the
   checkpoint in an independently administered monotonic store before declaring the
   backup generation restorable.
4. On restore, load the newest independently retained checkpoint first. Verify its
   signature and predecessor chain, then verify the backup artifact digest.
5. Open the restored database read-only and require every high-water value to be
   greater than or equal to the external frontier. Equal frontiers require exact
   digest equality. A lower or divergent frontier fails closed.
6. Re-evaluate revocation and supersession facts before enabling any writer or
   qualification consumer. Restoring an older binary never resurrects revoked or
   superseded evidence.
7. Only after the external frontier and current authorization policy agree may a
   new writer generation start. The first post-restore checkpoint must name the
   restored checkpoint as its predecessor.

## Complete-database replacement detection

A replacement database is accepted only when it belongs to the expected filename
and migration lineage and its canonical high-water manifest extends the independently
retained checkpoint. Replacing the file with a fresh database, an older backup, a
different candidate lineage or a same-height divergent frontier is a hard failure.

## Retention

Qualification receipts, revocations, supersession lineage, migration history,
external checkpoints and the backup generation needed to interpret them are retained
for the governing policy period. Pruning may remove externally referenced large
assets only after policy permits it and must never turn missing evidence into
positive proof. Revocation and supersession records are never pruned ahead of every
receipt they invalidate.

## Ownership and activation gate

The external checkpoint signer/store must be administered independently from the
kernel.evidence SQLite writer. Repository tests can validate the checkpoint format
and restore algorithm, but only an enrolled external service plus an actual restore
exercise can close the production anti-rollback gate.

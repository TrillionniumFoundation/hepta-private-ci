# kernel.evidence external checkpoint V1

## Scope

\`EvidenceExternalCheckpointV1\` is the repository implementation of the
logical anti-rollback boundary for the target \`qualification_evidence\`
domain. It binds:

- the exact prefix of the applied SQLx migration ledger;
- every immutable qualification receipt up to the retained sequence frontier;
- the frontier receipt ID and canonical envelope SHA-256;
- the capture time and a digest over the complete checkpoint body.

The checkpoint grants no authority. It becomes anti-rollback evidence only
when a caller retains it outside the SQLite database, WAL, host snapshot and
ordinary backup failure domain.

## Capture

After a successful qualification mutation:

1. call \`capture_external_checkpoint\`;
2. durably store the returned JSON in an independently controlled monotonic
   store, HSM-backed record, append-only operator ledger, or equivalent
   external frontier;
3. associate the checkpoint digest with the backup/snapshot that is eligible
   for restore;
4. do not advance the retained frontier until the external write has been
   independently acknowledged.

A local file beside \`hepta_evidence_2.sqlite\` is not an external checkpoint.

## Restore and replacement admission

Before admitting a restored or replacement evidence database, pass the latest
retained checkpoint to \`open_with_external_checkpoint\`. Store open first runs
the normal SQLite quick-check, migration checksum, schema and signed-row
verification. Checkpoint verification then rejects:

- a migration ledger behind the retained migration prefix;
- a changed migration prefix;
- a qualification receipt count or sequence behind the retained frontier;
- any changed, missing or reordered receipt in the retained prefix;
- a different frontier receipt ID or canonical envelope digest.

A newer database may extend the retained prefix. It may not rewrite it.

## Backup and retention

Backups remain transactionally consistent SQLite backups. Retain the matching
external checkpoint separately. Receipt supersession, receipt revocation and
issuer-key revocation are append-only lineage and must survive retention,
restore and export. Retention must never remove negative or revoked facts in a
way that converts missing evidence into support.

The V1 logical checkpoint covers the migration lineage and target qualification
domain. Existing governance, provider and AuthBus tables retain their current
native integrity checks and require the same transactionally consistent
backup. A future whole-database external attestation can extend this interface
without changing qualification receipt semantics.

## Failure handling

Checkpoint mismatch is corruption/rollback, not an infrastructure retry. Fail
closed, quarantine the database, retain both the rejected database and the
external checkpoint for diagnosis, and restore from a predecessor that verifies
against a retained frontier. Never lower or delete the frontier merely to make
a restore pass.

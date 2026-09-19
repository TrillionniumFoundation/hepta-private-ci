# Kernel evidence SQLite store V1

## Physical lineage

The current database filename is `hepta_evidence_2.sqlite`. Its migration set is
ordered and checksum-bound:

1. `0001_governance.sql`
2. `0002_provider_evidence.sql`
3. `0003_provider_host_binding.sql`
4. `0004_memory_mutation_shadow.sql`
5. `0005_channel_ingress_evidence.sql`
6. `0006_provider_ephemeral_input.sql`
7. `0007_provider_effect_evidence.sql`
8. `0008_provider_effect_ack_source.sql`
9. `0009_authbus_replay.sql`
10. `0010_authbus_outbox.sql`
11. `0011_qualification_evidence.sql`

Unknown, missing, incomplete, failed or checksum-mismatched migration rows cause
store open to **fail closed**. They are never treated as an empty, current or
repairable evidence lineage.

## Core integrity model

Governance decisions and receipts use unique identities, phase constraints,
payload hashes, foreign keys and update/delete denial triggers. Provider effect
intent, acknowledgement and uncertainty rows are separate immutable facts.
Transport acceptance is not inferred as terminal application; uncertainty is a
first-class record.

Migration `0011` adds the canonical append-only `qualification_evidence`
lineage. Every receipt binds an exact candidate commit/tree, claim class,
authenticated principal/key epoch/signing-key digest, role, canonical payload
and envelope digests, AuthBus message/sequence/expiry, observation/expiry and
correction/revocation lineage. Corrections and revocations append facts; they do
not rewrite or delete predecessors.

`open` performs SQLite quick-check, migration-ledger verification, schema
manifest checks, canonical qualification-row reconstruction/digest verification,
lineage validation, provider projections/effect validation and foreign-key
checks. `open_existing_read_only` requires an existing complete lineage and
never creates or migrates it.

## Concurrency

A transaction encloses each logical append and content-equivalence check.
Provider-effect operations also use one process-local mutex for clones of one
store. This mutex does not serialize other processes or independent opens.

AuthBus signed admission uses `BEGIN IMMEDIATE` to serialize replay and
capacity checks across independent handles. Qualification receipt append uses
the same replay registry **inside the same `BEGIN IMMEDIATE` transaction as
the immutable evidence insert**. A successful receipt therefore cannot consume
authentication replay state without durably creating the exact evidence row;
an exact signed retry is idempotent and semantic drift under the same
`evidence_id` conflicts.

## Backup, restore and retention requirements

SQLite integrity is not an external anti-rollback oracle. Production activation
requires the independently retained signed monotonic frontier specified in
[RECOVERY_FRONTIER_V1.md](RECOVERY_FRONTIER_V1.md).

Until a concrete external frontier backend is selected and qualified, operators
must not claim rollback-resistant production evidence. Backup/restore must:

- create a transactionally consistent database image while the writer is fenced;
- verify migration checksums, schema, canonical evidence rows and foreign keys;
- bind the image digest and evidence high-water to an externally signed
  monotonic frontier before calling the backup admissible;
- reject restore behind, conflicting with, or unable to prove equivalence to
  the independently retained frontier;
- retain correction/revocation lineage and never prune rows so missing evidence
  becomes positive proof.

These are activation prerequisites; repository source implements local
verification and the frontier contract, not an external checkpoint service.

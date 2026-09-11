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

Unknown, missing, incomplete, failed or checksum-mismatched migration rows cause
store open to **fail closed**. They are never treated as an empty, current or
repairable evidence lineage.

## Core integrity model

Governance decisions and receipts use unique identities, phase constraints,
payload hashes, foreign keys and update/delete denial triggers. Provider effect
intent, acknowledgement and uncertainty rows are separate immutable facts.
Transport acceptance is not inferred as terminal application; uncertainty is a
first-class record.

`open` performs SQLite quick-check, migrations and current-schema validation.
`open_existing_read_only` requires an existing complete lineage and never
creates or migrates it.

## Concurrency

A transaction encloses each logical append and content-equivalence check.
Provider-effect operations also use one process-local mutex for clones of one
store. This mutex does not serialize other processes or independent opens.

AuthBus signed admission uses `BEGIN IMMEDIATE` to serialize replay and capacity
checks across independent handles. Its sequence update commits before a receipt
returns. This transaction does not implement a general operations outbox.

## Backup, restore and retention requirements

Current source does not implement an external monotonic checkpoint or managed
retention service. A production operator must therefore:

- copy a transactionally consistent database and associated checkpoint;
- verify migration checksums and integrity after restore;
- reject restoration behind the independently retained frontier;
- retain supersession/revocation lineage;
- never delete rows in a way that turns missing evidence into positive proof.

These are operational prerequisites, not current repository claims.

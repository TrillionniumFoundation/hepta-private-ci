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

Migration `0011` adds the target qualification evidence contract as immutable
SQLite facts: exact candidate commit/tree binding, claim class, authenticated
issuer principal/key/role, detached Ed25519 signature, predecessor and receipt
revocation lineage, bounded asset references, expiry, durable issuer-key
revocations and the `IndependentDecisionReceiptV1` projection. Reopen verifies
canonical envelopes, row projections, signatures and projection bindings before
the store is admitted.

`open` performs SQLite quick-check, migrations and current-schema validation.
`open_existing_read_only` requires an existing complete lineage and never
creates or migrates it.

## Concurrency

A transaction encloses each logical append and content-equivalence check.
Provider-effect operations also use one process-local mutex for clones of one
store. This mutex does not serialize other processes or independent opens.

AuthBus signed admission uses `BEGIN IMMEDIATE` to serialize replay and capacity
checks across independent handles. Its sequence update commits before a receipt
returns. `enqueue_authbus_message` replaces direct admission for durable delivery: one transaction advances that same replay registry and inserts the immutable message. Its fenced lease/retry/ack operations redeliver messages, never unknown provider effects. See `hepta-authbus/SIGNED_ADMISSION.md` for retention and delivery semantics.

## Backup, restore, checkpoint and retention requirements

The store now exposes `capture_external_checkpoint`,
`verify_external_checkpoint` and `open_with_external_checkpoint`. The
checkpoint binds the exact migration prefix and the complete append-only
`qualification_evidence` prefix through the retained frontier. It has no value
as anti-rollback evidence if it is stored beside the database: production must
retain it in a separately controlled monotonic location and supply it when a
restored/replaced store is opened.

A production operator must:

- copy a transactionally consistent database and retain its matching external
  checkpoint outside the SQLite failure domain;
- use `open_with_external_checkpoint` on restore/replacement admission;
- verify migration checksums, schema integrity and signed qualification rows;
- reject any database whose migration or qualification prefix is behind or
  differs from the independently retained frontier;
- retain supersession, receipt-revocation and issuer-key-revocation lineage;
- never delete rows in a way that turns missing evidence into positive proof.

The logical checkpoint deliberately covers the qualification domain and
migration lineage. Existing governance/provider/AuthBus subdomains continue to
use their native integrity and migration checks and still require a
transactionally consistent backup. A stronger external whole-database
attestation may be layered above this interface without changing qualification
receipt semantics.

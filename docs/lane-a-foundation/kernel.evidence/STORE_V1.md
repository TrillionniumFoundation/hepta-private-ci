# Kernel evidence SQLite store and publication lineage

The historical path remains `STORE_V1.md`, but the current production recovery
identity is authenticated snapshot V2. This document describes the actual
checksum-bound SQLite lineage and publication protocol; it does not grant
activation, acceptance or release authority.

## Physical lineage

The database filename is `hepta_evidence_2.sqlite`. The ordered migration set is:

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
12. `0012_authbus_recovery.sql`
13. `0013_recovery_frontier_acceptance.sql`
14. `0014_evidence_publication.sql`
15. `0015_evidence_trust_acceptance.sql`
16. `0016_qualification_auth_provenance.sql`
17. `0017_frontier_repair_publication.sql`

Unknown, missing, failed, reordered or checksum-mismatched migrations cause open
to fail closed. Production never treats an unknown lineage as empty or
repairable and never runs migrations through the restricted runtime handle.

The ordinary open paths also compare all 17 publication/trust schema objects
from migrations `0014` and `0015` with their complete compiled definitions,
including trigger bodies, conditions and table constraints. Matching invariant
words in comments or a disabled `WHEN 0` trigger is insufficient. Each stored
definition is bounded to 64 KiB before materialization. Only unquoted layout
whitespace and the terminal semicolon are normalized; quoted content and
comments are retained. Migration bytes and migration checksums are unchanged.
This check concerns local schema integrity, not authenticated external truth
or protection against rollback of the entire database and its local metadata.

The eight governance/provider invocation immutable UPDATE/DELETE triggers from
`0001`/`0002` also use complete compiled definitions. Those trigger definitions
remain unchanged through migration `0017`; later table ALTERs are not interpreted
as if their original CREATE TABLE text were the current schema. The remaining
legacy table and trigger checks retain their existing validation paths and do
not inherit a complete-definition claim from these selected guards.

## Qualification and authenticated provenance

Migration `0011` owns the append-only qualification lineage, immutable
`evidence_recovery_identity`, indexes and database-level update/delete denial
triggers. Each row binds exact candidate commit/tree, claim class, receipt kind,
issuer role/principal/key epoch/signing identity, canonical payload/envelope
digests, AuthBus message/sequence/expiry, observation/expiry and lineage.

Migration `0016` adds the original admission signature and the verified trust
registry generation/digest. New production rows require those fields.
Historical rows whose original signatures were not stored remain interpretable
history, but absence is not reconstructed and such rows cannot satisfy
production authenticated-snapshot V2.

`authenticated_row_sha256` commits all authority-relevant row fields, including
signature and trust provenance. Recovery no longer commits only the envelope
digest.

## Transaction boundaries

Qualification append executes under one `BEGIN IMMEDIATE` transaction:

1. revalidate the sealed issuer/trust identity;
2. authenticate the exact canonical envelope and subject;
3. reject replay, expiry, lineage or semantic conflict;
4. advance durable AuthBus replay;
5. insert the immutable qualification row;
6. create the publication intent when the store is enrolled;
7. commit all facts together.

A precise authenticated retry is idempotent. Reusing an evidence or batch
identity with changed semantics is a conflict.

Verification and recovery use explicit read transactions. Snapshot V2 reads the
migration set, store identity, authenticated qualification commitment and
AuthBus replay frontier from the same SQLite snapshot. Recovery and production
provenance scans use keyset pages. Before canonical startup reconstruction
materializes rows, operational preflight enforces at most 1,000,000 rows, at
most 512 MiB of canonical envelope bytes, the 256 KiB per-envelope limit and
the fixed 64-byte AuthBus signature width. An oversized but syntactically valid
database therefore fails closed before the full decoder allocates its result.

## Recovery and trust acceptance

Migration `0013` stores immutable accepted external frontiers. Migration `0015`
stores accepted monotonic trust registry generations and binds each generation
to the accepted external frontier.

Production calls `accept_production_generation_at_snapshot()` under one
`BEGIN IMMEDIATE` transaction. The store recomputes the exact expected
authenticated snapshot, requires the next trust generation and matching
predecessor digest, then records trust plus frontier acceptance atomically.
Snapshot drift, lower/skipped generation, changed registry semantics or
frontier mismatch fail closed.

## Durable publication protocol

Migration `0014` owns:

- the singleton publication owner lease and monotonically increasing owner
  generation;
- immutable publication batch identity, snapshot and proposed frontier;
- per-evidence publication intents;
- strict state-transition and no-delete triggers.

The state model is:

```text
prepared -> dispatching -> acknowledged
                      \-> indeterminate
indeterminate -> acknowledged
```

A stale owner generation cannot mutate a batch. Before external CAS, the batch
is durable and bound to the exact authenticated snapshot and intended next
frontier. If CAS outcome is uncertain, the batch remains `indeterminate`.
Recovery reads authenticated external latest state:

- latest equals the proposed frontier: recover acknowledgement;
- latest equals the expected predecessor: retry the same batch under the
  current fenced owner;
- latest differs: conflict and operator recovery, never blind replay.

Local acknowledgement verifies the durable backend acknowledgement and commits
frontier acceptance, batch completion and intent completion atomically.

## Separate repair ledger

Migration `0017` retains exact signed repair authorization, authority nonce,
current/target frontiers, dispatch fence and immutable event chain. It is a
library capability; Agentd does not attach an external repair publisher.
`verify_frontier_repair_ledger()` must succeed before such attachment. It reads
schema, capacity, operations and events in one transaction, compares complete
schema definitions with the compiled migration, rejects orphan events, bounds
combined canonical bytes and event count before decoding, and checks event
version, hash chain, terminal timestamp and the signed target backend fence.
Ordinary store open does not replace this explicit repair attachment gate.

## Runtime authority

Production performs a read-only existing-lineage preflight, including SQLite
quick check, migration ledger, schema manifest, canonical row reconstruction,
authenticated-provenance verification, trigger inventory, publication/trust
state and foreign keys.

Normal runtime then opens the same file through the restricted SQLite
authorizer. The authorizer denies DDL, attach/detach, migration-ledger mutation,
extension loading and write-capable pragmas. Immutable-row triggers remain
defense in depth. Typed append/publication operations are the only supported
authoritative writers.

## Backup and restore

A production frontier binds a backup manifest. Admission verifies:

- the actual backup object byte length and SHA-256;
- private regular-file ownership, link count, path and stable file/directory
  identity during the read;
- storage backend identity and durable acknowledgement;
- governed source-to-executable build provenance;
- a successful restore witness binding restored object, restored snapshot and
  SQLite integrity-check digest;
- generation, backend, source, executable and freshness equality with the
  signed frontier.

The repository implementation supplies these validators and the publication
driver. It does not prove that an independent storage device, coherent
cross-host locks, power-loss durability, an operator restore drill or an
external witness actually exist for a deployment.

## Retention and long-running history

The external frontier backend uses an active tail, immutable linked segments and
a self-authenticating atomic latest index. The active tail rolls at 1024 records
or 16 MiB. Sealed segments and their metadata are never rewritten or deleted by
normal capacity management. A stale index is reconstructed from authenticated
history.

Capacity observation reports segment count, archived/active records and bytes,
record/byte headroom and alert state. Operators must respond before capacity or
platform limits are reached; clearing history is not a valid recovery action.

Qualification corrections and revocations remain append-only. Retention must
never make missing evidence become positive proof and must preserve replay,
trust, accepted-frontier and publication identities across restore.

## Current claim boundary

Source implementation of the lineage, snapshot, publication and segmented
backend exists. Exact-candidate workflow success, independent storage
deployment, real target-platform backup/restore and power-loss qualification,
independent acceptance, canary and release remain separate receipt-bearing
gates.

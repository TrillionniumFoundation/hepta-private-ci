# ADR-0001: ancestry-safe retention and pruning

Status: accepted design; destructive pruning implementation and deployment qualification remain pending.

## Context

`cognitive.store` is append-only at the authoritative Memory/source/fact level. Correction and forget add successor revisions; they do not rewrite history. Unbounded history cannot remain indefinitely in the hot SQLite profile, but deleting old rows in place would break predecessor proofs, source citations, tombstone non-resurrection and exact-cut recovery.

## Decision

Retention uses immutable generations, never ad-hoc row deletion.

1. **Hot generation.** The active SQLite generation retains all current heads, tombstones, source revisions required by visible heads, unresolved operation/outbox state and a bounded ancestry window.
2. **Checkpoint generation.** Before any cold movement, the owner creates a complete deterministic checkpoint receipt binding schema digest, exact current cut, head set, tombstone frontier, source/fact/KG frontiers and every archived segment digest.
3. **Cold immutable segments.** Eligible historical rows are serialized in canonical key order into content-addressed, encrypted immutable segments. A segment contains complete predecessor/citation closure for its declared range and a signed owner manifest.
4. **Published successor.** A fresh private SQLite generation is rebuilt from retained hot rows plus checkpoint anchors, integrity-checked, compared to the same current semantic cut, then atomically published through the existing active-generation pointer.
5. **Recovery.** Recovery must authenticate the current checkpoint and every referenced segment. Missing, revoked or ambiguous cold history makes historical reads unavailable; it never fabricates ancestry or silently drops a tombstone.

No in-place `DELETE`, `VACUUM`-as-erasure or backup rotation is allowed to define semantic pruning.

## Eligibility

A row may leave the hot generation only when all conditions hold:

- it is not a current head, active grant, pending operation, current projection source or unresolved reconciliation dependency;
- every live descendant and citation path remains provable through retained rows or one authenticated checkpoint/segment chain;
- its retention policy permits movement;
- legal/privacy hold state is resolved;
- a complete export/delete provenance record has been committed where applicable;
- the target segment and rebuilt generation both pass deterministic oracle checks.

Tombstones remain represented in the hot cut or in an authenticated non-resurrection frontier. Their payload may be redacted under policy, but the stable identity, revision and terminal disposition must remain provable.

## Failure semantics

- Failure before successor publication leaves the current generation authoritative.
- A published-pointer ambiguity is `Indeterminate`; do not delete either generation.
- Segment upload acknowledgement loss is reconciled by content digest; never upload a semantically different replacement under the same segment id.
- Missing cold storage prevents retirement of the predecessor generation.

## Physical erasure

Logical forget, hot pruning, cold-segment deletion, backup expiry, derived-artifact revocation and model unlearning are distinct operations. Physical erasure is complete only when the privacy runbook has receipts for every applicable storage class. Historical audit metadata may be retained only when policy permits and must not retain prohibited payload.

## Required implementation before activation

- canonical segment and checkpoint schemas;
- archive writer with bounded memory and crash-safe staging;
- exact-cut rebuild oracle and restore drill;
- retention policy owner and hold interface;
- deletion propagation to backups, projections and derived artifacts;
- maximum-growth and recovery-time qualification on the selected host.

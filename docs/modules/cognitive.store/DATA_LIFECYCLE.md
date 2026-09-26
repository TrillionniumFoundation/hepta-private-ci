# cognitive.store data lifecycle

## Data classes

| Class | Authority | Creation | Update model | Retirement |
|---|---|---|---|---|
| Source revision | `source_ledger` | admitted with observed bytes/digest | immutable | retained for cited lineage or archived with proof |
| Memory revision | `memory_revisions` | remember/correct/forget transaction | immutable successor | tombstone plus policy-governed archive/erasure |
| Memory head | `memory_heads` | CAS with revision transaction | mutable projection | rebuilt from revision chain |
| Fact set | `kg_revision_*` | atomically with owning Memory revision | immutable successor set | follows owning revision lifecycle |
| KG/read projection | projection tables/FTS | deterministic publication | replace complete generation | rebuildable; never authority |
| Production provenance | local event/outbox journal | same transaction as mutation | append-only terminal transition | retained through reconciliation/audit policy |
| Recovery witness | external trusted host | exact coherent cut | replace with newer signed witness | old witness revoked/retired outside Agent home |
| Authority state | external trusted host | signed monotone revision | exact signed successor | revocation terminal for that writer generation |
| SQLite WAL/journal | physical owner | transaction engine | checkpointed | removed only after verified checkpoint and file identity checks |
| Backup/recovered generation | backup owner / active pointer | bounded copy/checkpoint | immutable generation | policy expiry only after newer cut is authenticated |
| Derived dataset/artifact | learning/artifact owners | cited export | owner-specific successor/revocation | revoke and rebuild; not erased by a Memory tombstone alone |

## State transitions

### Remember

A verified source and first Memory revision commit atomically. The fact set and complete projection successor are part of the same transaction. A production receipt binds authority, epochs, writer generation, input digest, source revision and final write digest.

### Correct

Correction requires the exact current revision. It appends a successor Memory revision and complete successor fact set, then CAS-advances the head. The predecessor remains immutable and visible only to authorized historical reads.

### Forget

Forget appends a tombstoned successor with an empty fact set. Current reads and derived current projections exclude the former live payload. Forget does not by itself erase database pages, WAL history, backups, exported datasets or trained parameters.

### Archive/prune

Archive follows ADR-0001. The current semantic cut must remain identical before and after the generation rebuild. Checkpoint and segment receipts preserve ancestry and tombstone non-resurrection.

### Physical erase

Physical erase is policy- and owner-specific. The coordinator records dispositions for active SQLite generations, retired generations, WAL/journal, backups, cold segments, caches, exports and derived artifacts. Any unavailable owner produces an explicit pending/indeterminate disposition, not a false success.

## Restore rule

A technically valid SQLite image is not necessarily current. Writer recovery requires an independently retained signed exact-current-cut witness and live external authority. An older internally valid image is rejected even if `PRAGMA integrity_check` succeeds.

## Invariants

- one authoritative writer per Agent store generation;
- no resurrection after a current tombstone;
- scope and owner never change across Memory revisions;
- projections never become source facts;
- no external-effect authority in read, mutation or bootstrap receipts;
- unknown or ambiguous retention/deletion outcomes remain explicit.

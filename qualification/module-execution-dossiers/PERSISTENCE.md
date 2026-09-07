# Physical state, transactions and recovery contracts

Scope: a proposed owner-reviewed pilot profile under the existing module design. No product store is implemented or deployed by this text or its SQL fixture. Existing data-authority registries and native formats prevail until a reviewed migration admits a new profile.

## 1. Observed source and implementation choice

The inspected `hepta-cognitive-store/src/lib.rs` contains an in-memory `CognitiveStore` backed by `BTreeMap`, with a maximum of 16,384 live record IDs. It is a semantic oracle, not a durable backend. The pilot implementation adds an owner-scoped durable adapter and tests observational parity with compatible `append`, `get` and `snapshot_records` behavior.

By contrast, learning already exports `DurableLedger`, anchors/recovery/inspection, artifacts export candidate-payload and registry-snapshot storage, and Neuron exports `SparseJournal` and `JournalAnchor`. Preserve those native formats and anchored recovery; do not replace them with a parallel Python product ledger or silently reinterpret them as SQLite rows.

The cognitive pilot uses the accompanying `COGNITIVE_STORE.sql` as a qualification DDL and state-machine fixture. Before native use the owner must bind the schema digest, existing domain-to-table mapping, migration/profile ID and consumer compatibility. This does not add a new canonical fact owner.

## 2. Cognitive store format

The proposed tables encode one existing cognitive owner: `frontier` tracks scope sequence and revision digest; `event` holds immutable bounded revisions; `current_record` is a rebuildable latest-revision projection; `revocation` holds monotonically appended exclusion events; `mutation` stores idempotency receipts; `publication_intent` stores owner-local pending publication metadata. A local publication intent is transaction metadata of the cognitive owner, not a replacement for the kernel's canonical cross-owner outbox.

IDs retain the canonical StableId contract. Digests are BLOBs of exactly 32 bytes. SQLite INTEGER counters use the nonnegative signed-64 pilot subset; out-of-range native u64 values reject or migrate through a separately versioned format. No silent wrapping or narrowing is permitted. Payload bytes are already scope/purpose-approved and bounded; general receipts carry digests, not copied private content.

Foreign keys and checks prevent missing or wrong-record current references, non-integer counters, invalid revisions and malformed digests. Publication intents refer to a committed local mutation identity; destination acceptance is not implied by their presence. The native adapter additionally validates full domain semantics, predecessor chains, source supports, current grants, privacy and resource bounds. SQL schema validation alone does not authenticate a writer.

## 3. Mutation algorithm and acknowledgement

Open with foreign keys enabled, `journal_mode=WAL`, `synchronous=FULL`, a bounded busy timeout and a supported local filesystem. Record actual returned PRAGMA values and runtime version. A failure to obtain the required durability profile blocks write readiness.

For one bounded mutation: authenticate owner and scope; preflight payload and input bounds; begin immediate transaction; read the current fence/frontier; resolve `(scope,operation_id)` first; return the prior receipt on equal semantics or Conflict on different semantics; for a new identity compare expected predecessor and preflight every counter increment against that locked state; append event revision; update the current projection; append mutation receipt then local publication intent; advance the frontier; commit; persist the required acknowledgement witness; only then acknowledge externally. No network/provider call occurs while the database writer transaction is held. A retry lookup precedes the new-write predecessor check so an acknowledgement-lost retry can recover its original receipt after the frontier advanced. Returned historical evidence does not grant a new effect.

If witness publication fails after commit, recovery uses the original operation identity and anchored frontier. It must not claim the mutation never occurred. Another owner cannot bypass this protocol by opening the file directly. Read-only ports receive owner-created snapshot handles, not writer connections.

## 4. Source corrections and deletion

A correction appends a linked revision; it does not rewrite the original event. Tombstones and revocations carry source/range cutoffs and a monotonically anchored frontier. Every read, replay, context attachment, graph build and artifact eligibility check overlays the current exclusion frontier. A frozen run snapshot does not freeze revocation.

Logical exclusion, physical source/asset erasure, projection/cache rebuild and parameter unlearning are separately tracked. Full retraining or artifact revocation is the fallback when selective unlearning is unsupported. Hash-only tombstones must not expose recoverable personal payloads. Restore of an old backup never reopens reads until current exclusion and authority frontiers have been applied.

## 5. Backup, WAL, compaction and rotation

A live SQLite database is not backed up by copying only its main file while ignoring its WAL. Use an owner-approved consistent backup mechanism and retain a manifest of schema, source cut, exclusions and acknowledgement anchors. Restore into an off-route target, validate integrity/foreign keys and replay required current revocations before publishing readers.

For native learning/neural journals, retain the selected format's frame checks, locks, anchors and acknowledged-history requirements. A damaged or truncated acknowledged segment fails recovery; never fall back from anchored to unanchored opening. Rotation publishes a new segment manifest atomically with a predecessor link and a verified continuity witness. Delete a retired segment only after retention, backup and lineage obligations permit it.

Compaction cannot erase evidence needed to reconcile unknown effects. Projection garbage collection is different from source deletion. Resource limits include live IDs, cumulative bytes, WAL age, pinned snapshots, orphan artifacts and pending publication age. Backpressure happens before mutation; saturation does not create unlimited retries.

## 6. Migrations and rollback

Freeze a deterministic transformation, schema/profile digest and rollback strategy. Stop new writes; drain local publication work to a watermark; resolve/quarantine unknown effects; fence old writer; snapshot exact range; migrate off-route; validate counts, digests, source invariants, tombstones, readers and bounds; establish fresh new fence; atomically publish route/generation.

Before cutover, an intact compatible predecessor may resume under fresh authority after current revocation overlay. After new writes have been admitted, rollback must preserve the successor delta: drain and fence the new writer, migrate its accepted changes back through a validated reverse/forward-compatible path, or quarantine. Restoring the pre-cutover snapshot alone would lose acknowledged writes and is not rollback.

The same-owner cardinality-preserving handoff schema remains a limited profile. Split, merge, owner transfer and multiple shards require the composite obligations in `ORGAN_EVOLUTION.md`; no shared receipt may silently widen its meaning.

## 7. Required fault matrix

Inject failure before/after transaction start, predecessor read, event append, projection/outbox update, commit, witness, acknowledgement and process restart. Cover two-writer race, duplicate/altered operation identity, stale fence, counter overflow, disk full, corrupt frame/schema, nonempty WAL, cancellation, revoke during read, restore before forget, missing segment and migration cutover at each phase.

The expected result is either the exact previous committed state or one recoverable committed successor; never invented success, duplicated effects or partially published state. A local Python/SQLite fixture proves only its tested database behavior in this environment. Native fault injection, target filesystem power-loss behavior and a production caller require separate receipts.

References: SQLite isolation and WAL documentation, https://www.sqlite.org/isolation.html and https://www.sqlite.org/wal.html. The chosen FULL/backup/locking profile still requires target-specific qualification; a PRAGMA is not a hardware durability certificate.

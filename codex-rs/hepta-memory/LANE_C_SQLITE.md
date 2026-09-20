# Lane C: the existing SQLite owner

`CognitiveStore::lane_c_snapshot` projects the existing `cognitive_1.sqlite3`
database into `hepta-cognitive-types::CognitiveSnapshot`. Existing memory/source
write APIs remain the only writers. This adapter adds no database, migration,
background synchronization, or replacement identity format. The in-memory
`hepta-cognitive-store` V2 implementation is not a durability backend.

The host first derives `CognitiveAccess` and an exact `CognitiveScope` from its
authenticated identity. The adapter authorizes before querying. A workspace
request does not implicitly include agent-private or other workspace memories.
All heads, immutable revisions, citations, source counts, fact-set counts, and
graph generation are read in one SQLite transaction.

`knowledge_fact_ledger` is the authoritative fact-set subledger inside this same
owner. Its physical rows are `kg_revision_fact_sets`, `kg_revision_entities`,
and `kg_revision_relations`, all keyed by the owning `(memory_id,
memory_revision)` and committed with that Memory revision. It has no independent
fact head or writer. Corrections publish a complete fact set for the successor
Memory revision; tombstones publish an empty fact set. `kg_projection` and the
`knowledge.graph` generation are derived, rebuildable projections of these
Memory-bound facts and are never the fact source of truth.

| Existing owner value | Lane C representation |
| --- | --- |
| `memory:v2:<hash>` and revision | Unchanged record ID and revision |
| `source:v1:<hash>` and source content SHA256 | Citation ID and digest |
| Verified, currently valid active head | Live `Fact`, content digest only |
| Provisional, expired, or future active head | Excluded from visible records |
| Committed tombstone | Tombstone, effective immediately even if future-dated |
| Ordered immutable revision chain | Canonical predecessor record digest |
| Number of scoped memory revisions / source rows / tombstones / fact sets | Corresponding owner frontiers |
| Scoped SQLite graph generation (zero when absent) | Graph generation plus one |
| Number of scoped memory revisions | Snapshot generation plus one |
| Owner UUID and scope projection-key digest | `cognitive:<UUID>:<SHA256>` scope ID |

The two generation offsets preserve the nonzero newtype contract; they are not
wall-clock timestamps. Visibility can change when a validity interval expires
without a write, so callers compare the complete snapshot digest and frontiers,
not only snapshot generation. Broken ancestry, a nonlatest head, invalid record
metadata, and tombstone resurrection fail closed. All returned values retain
`DENY_ALL` effect authority.

`DurableCognitiveSnapshot::read(ReadRequestV2)` runs the new cognitive-read
implementation against this owner-acquired cut. The caller supplies result and
encoded-byte bounds. It can intersect these digest-only records with the
existing scoped retrieval API and fetch matching content through the same
store. Before delivery, compare each fetched record's exact revision and content
digest, call `revalidate_lane_c_snapshot`, and recheck host authority/generation.
Revalidation detects intervening corrections, deletions, newly appended source
evidence, projection changes, and changes caused by validity time. It rejects
clock regression. A subsequent concurrent write remains possible: this API
returns a historical read cut and does not grant a lease over future effects.

`bind_context` optionally binds an externally frozen
`LaneCGenerationVectorV1`. All five cognitive-owned components must exactly
match the cut. The host must obtain prompt, compact, model, retrieval-profile,
and authority values from their actual owners; the adapter supplies no defaults.
Acquisition time must match the observed second, and the lease is bounded to
five minutes. These are crate-native APIs; this change does not register V2
types as a cross-module wire format or authorize arbitrary caller-supplied
generation vectors.

Reopening with existing `CognitiveStore::open` reconstructs the same cut from
durable rows. `cut_digest` can be retained independently and compared using
`revalidate_lane_c_cut` after reopen, detecting an older internally valid backup
or any other changed cut. The witness is an exact equality fence, not an
ordering proof, signature, or proof that the latest witness was retained.
Hosts must authenticate and preserve it independently if rollback protection is
required. Descriptor-bound writable `open_with_recovery` is now a distinct
source-implemented admission path. It acquires an exclusive store fence, copies
retained database/WAL/journal descriptors into a fresh private generation,
requires an independently authenticated exact-current-cut anchor and externally
verified production authority/fence, runs schema/integrity checks, checkpoints
the copy, and atomically publishes the active-generation pointer. Ordinary
`CognitiveStore::open` remains weaker because it has no independent currentness
proof and must never be used as a recovery fallback after admission failure.

Whole-scope `lane_c_snapshot` remains bounded to 16,384 immutable revisions,
65,536 citations, and 65,536 source rows; exceeding those pilot bounds returns
`Unavailable`. For larger scopes, `lane_c_snapshot_page` keyset-pages at most
512 current heads and loads complete ancestry/citations only for the selected
heads (16,384 ancestry revisions / 65,536 citations per page). Its continuation
binds the global memory/source/tombstone/fact/KG frontiers, citation count,
complete ordered head set and observation time. Any intervening owner mutation
or validity-time change rejects the continuation rather than mixing cuts.
Authoritative immutable history is retained; paging is bounded materialization,
not destructive pruning.

Production semantic writes use the existing `cognitive_local_events` / `cognitive_local_outbox` append-only journal as their provenance ledger rather than introducing another table or database. `ProductionCognitiveMutationCapability` inserts the admitted intent, applies the authoritative source/Memory/fact/projection mutation, and appends the committed outcome under the same `BEGIN IMMEDIATE` transaction. The production receipt binds the external grant and epochs, writer generation, semantic input digest, expected predecessor, committed source revision and final write digest. A failed semantic mutation therefore leaves neither a domain change nor an orphan provenance admission.

`lane_c_snapshot_tests.rs` exercises actual owner writes, correction ancestry,
proof-bound paging, committed deletions, scope and verification/time filters,
context binding, and restoration of an older valid SQLite backup.
`cognitive_store_recovery_tests.rs` exercises descriptor-bound writable
recovery, exclusive fencing, stale/current anchors and hostile file identities.
Run with `just test -p codex-hepta-memory`; exact-candidate CI also records the
durable performance profiles described in the module guide.

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
required. This adapter does not weaken `open_with_recovery`: its descriptor-safe
SQLite VFS and independent currentness prerequisites remain required and that
separate admission path still fails closed until implemented.

## Bounded full snapshots and lineage paging

Full `CognitiveSnapshot` materialization remains bounded to 16,384 immutable
revisions, 65,536 citations, and 65,536 source rows in one exact scope;
exceeding a bound returns `Unavailable` without a partial snapshot. Those limits
are intentionally unchanged for the product read path.

`CognitiveStore::lane_c_lineage_page` is the bounded long-history traversal
primitive. It reads from the same SQLite owner and:

- pages by complete memory identity, never by arbitrary revision row, so one
  memory's predecessor chain is never split across page boundaries;
- returns the durable `MemoryRevisionRecord` values rather than laundering
  provisional/verification state into a visible fact;
- carries the global owner frontiers, including the tombstone frontier, on every
  page;
- sandwiches each page between two exact logical `CognitiveRecoveryAnchor`
  captures and rejects the page if any owner state changed during acquisition;
- lets the caller pass the previous page's exact state digest into the next
  request, so pages from different cuts cannot be silently combined;
- bounds one page to 256 memory identities and 4,096 immutable revisions and
  fails rather than emitting a partial ancestry chain.

This paging API does **not** authorize physical pruning. Immutable source,
memory, citation, fact and tombstone rows remain authoritative until a future
archive/pruning format carries a durable predecessor anchor and proves deletion
frontier continuity across removed segments. Compaction or a projection must
not delete authoritative history merely because paged traversal exists.

## PERF-DURABLE measurement source

`examples/cognitive_store_perf.rs` is the executable measurement harness for the
canonical owner. It exercises real durable memory/KG transactions, reports
SQLite DB+WAL+SHM growth, materializes the owner snapshot, reopens the store and
revalidates the exact cut. It prints a machine-readable
`hepta.perf-durable.cognitive-store.v1` record with commit latency distribution,
snapshot/reopen/revalidation durations and observed frontiers.

The harness is source, not a stored performance result. Run it on the named
target host and retain exact source SHA, binary/artifact identity, host profile
and stdout before making latency, throughput or capacity claims. For example,
from `codex-rs`:

```sh
cargo run --locked -p codex-hepta-memory --example cognitive_store_perf -- 1000
```

`lane_c_snapshot_tests.rs` exercises actual owner writes, correction ancestry,
reopen, committed deletions, scope and verification/time filters, context
binding, and restoration of an older valid SQLite backup.
`tests/lane_c_paging.rs` exercises whole-history pagination, tombstone-frontier
continuity and stale-cut rejection. Run with `just test -p codex-hepta-memory`.

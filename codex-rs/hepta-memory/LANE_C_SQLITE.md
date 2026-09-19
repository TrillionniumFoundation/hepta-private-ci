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
| Verified, currently valid active head | Live `DURABLE_SQLITE_MEMORY_KIND` = `Fact`, content digest only |
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

The current durable schema has no persisted memory-kind discriminator.
`DURABLE_SQLITE_MEMORY_KIND` therefore explicitly fixes this adapter to
`MemoryKind::Fact`; callers may not infer Episode/Preference/Procedure from the
generic cognitive type enum without an owner schema migration.

`DurableCognitiveSnapshot::read_ids(ReadIdsRequestV1)` runs the typed-local
exact-ID cognitive read port against this owner-acquired cut. The caller supplies
at most 512 IDs, selected projection fields, and an encoded-byte bound. Missing
IDs are explicit and an exact-ID request is all-or-error rather than a prefix.
The legacy `read(ReadRequestV2)` remains available as a bounded compatibility
projection, but product retrieval no longer intersects candidates with its
first-1,024-record prefix.

Agentd retrieves bounded candidates, validates their exact ID/revision/content
digest through `read_ids`, and calls `revalidate_lane_c_snapshot` before
response publication. The native model consumer additionally requires the
capability `cognitive.context.revalidate@1`; immediately before physical
`TurnStart` the owner reacquires a current snapshot and verifies the selected
ID/revision/content bindings. Correction, deletion and validity-time changes
therefore fail closed at final use. A subsequent concurrent write remains
possible: these checks are current observations and do not lease future effects.

`bind_context` optionally binds an externally frozen
`LaneCGenerationVectorV1`. All five cognitive-owned components must exactly
match the cut. The host must obtain prompt, compact, model, retrieval-profile,
and authority values from their actual owners; the adapter supplies no defaults.
Acquisition time must match the observed second, and the lease is bounded to
five minutes. These are crate-native APIs. `read_ids_v1` is the typed-local ModulePort shape;
its canonical bytes and the V2 canonical bytes are not cross-process wire
protocols. Arbitrary caller-supplied generation vectors remain unauthorized.

Reopening with existing `CognitiveStore::open` reconstructs the same cut from
durable rows. `cut_digest` can be retained independently and compared using
`revalidate_lane_c_cut` after reopen, detecting an older internally valid backup
or any other changed cut. The witness is an exact equality fence, not an
ordering proof, signature, or proof that the latest witness was retained.
Hosts must authenticate and preserve it independently if rollback protection is
required. This adapter does not weaken `open_with_recovery`: its descriptor-safe
SQLite VFS and independent currentness prerequisites remain required and that
separate admission path still fails closed until implemented.

Materialization is bounded to 16,384 immutable revisions, 65,536 citations, and
65,536 source rows in one exact scope; exceeding a bound returns `Unavailable`
without a partial snapshot. This first adapter does not promise a fixed latency
or unbounded lifetime retention. Retention/paging must preserve predecessor
proofs and deletion frontiers before those limits can be increased safely.

`lane_c_snapshot_tests.rs` exercises actual owner writes, correction ancestry,
reopen, committed deletions, scope and verification/time filters, context
binding, and restoration of an older valid SQLite backup. Run with
`just test -p codex-hepta-memory`.

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

`CognitiveStore::lane_c_authoritative_provider` acquires an immutable owner cut and binds it to `LaneCAuthorityContextV1`; `read_authoritative` is the product-facing reader. The SQLite owner fills memory/source/tombstone/knowledge-fact frontiers and graph generation from the same transaction. The host supplies only purpose, serving generation and authority epoch. Prompt/model/compact identities are intentionally outside this module-specific authoritative subset and are never fabricated here.

The returned `LaneCAuthoritativeSnapshotProvider` exposes no writer or moving/current-state query interface. Before final context consumption, `revalidate_lane_c_authoritative_provider` reacquires the canonical owner cut, requires exact equality of snapshot/frontiers, preserves the original lease expiry, and rebuilds the authoritative envelope against current host authority. `AuthoritativeReadResultV1::revalidate_for_current_snapshot` then requires the same provider, generation-vector digest, snapshot digest, request binding and unexpired original lease. Agentd additionally fences the lifecycle authority epoch before publication. Intervening corrections, deletions, source/frontier advances, projection changes, lease expiry or host epoch changes fail closed.

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
reopen, committed deletions, scope and verification/time filters, authoritative provider binding/final-use revalidation, and restoration of an older valid SQLite backup. Run with
`just test -p codex-hepta-memory`.

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

`DurableCognitiveSnapshot::read(ReadRequestV2)` remains the lower-level typed
reader for callers that already own an exact snapshot-bound request.
`DurableCognitiveSnapshot::read_current` is the canonical SQLite product seam:
it constructs the `ReadRequestV2` snapshot digest from the owner-acquired cut,
so product code cannot substitute a caller-selected expected snapshot digest.
`CognitiveStore::revalidate_lane_c_read` then verifies that the resulting read
receipt belongs to that exact cut, retains `DENY_ALL`, and reacquires the entire
owner cut before publication. `revalidate_lane_c_snapshot` remains available
for callers that need only cut equality.

The caller can intersect these digest-only records with the existing scoped
retrieval API and fetch matching content through the same store. Before
publication, compare each fetched record's exact revision and content digest,
call `revalidate_lane_c_read`, and recheck host authority/generation. Revalidation
detects intervening corrections, deletions, newly appended source evidence,
projection changes, and changes caused by validity time. It rejects clock
regression.

The native Agentd/App Server product path adds one more final-use boundary: the
worker performs a second generation/lifecycle-fenced Agentd cognitive-context
read after provider `thread/start` and immediately before durable dispatch plus
`turn/start`. It compares the first and refreshed snapshot/read digests, omitted
count, admitted items and stable planner semantics; mismatch fails before model
dispatch, and only the refreshed snapshot is attached. This closes the previous
multi-RPC stale-read window without pretending that a historical SQLite cut is
an atomic lease over writes that can happen after the final check.

`bind_context` optionally binds an externally frozen
`LaneCGenerationVectorV1`. All five cognitive-owned components must exactly
match the cut. The host must obtain prompt, compact, model, retrieval-profile,
and authority values from their actual owners; the adapter supplies no defaults.
Acquisition time must match the observed second, and the lease is bounded to
five minutes. These are crate-native APIs; this change does not register V2
types as a cross-module wire format or authorize arbitrary caller-supplied
generation vectors.

`AuthoritativeCognitiveSnapshotProvider` is therefore not silently implemented
by the SQLite owner. Its full generation-vector contract includes values owned
outside memory (for example model/tokenizer/template/tool identities). A host
may use `bind_context` and that abstraction only when it actually possesses a
coherent externally frozen vector. The ordinary SQLite product read remains the
durable `lane_c_snapshot` / `read_current` / `revalidate_lane_c_read` path.

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
binding, and restoration of an older valid SQLite backup.
`hepta-agentd/src/cognitive_context_tests.rs` verifies that a committed
withdrawal changes both snapshot and read receipt, and
`hepta-infer-worker-host/src/native_app_server_tests.rs` verifies that final-use
comparison rejects snapshot/read/item/planner drift while allowing a refreshed
short-lived planner receipt for unchanged context. Run focused checks with
`just test -p codex-hepta-memory -p codex-hepta-agentd -p codex-hepta-infer-worker-host`.

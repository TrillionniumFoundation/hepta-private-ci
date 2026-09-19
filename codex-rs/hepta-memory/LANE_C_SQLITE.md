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

`DurableCognitiveSnapshot` no longer exposes a product read shortcut.
Instead, `authoritative_provider` binds this exact immutable owner cut to an
`AuthoritativeReadGenerationVectorV1` and
`SnapshotAcquisitionRequestV1`. The vector contains only state that this read
actually consumes and that the owner/host can truthfully revalidate: scope,
purpose, memory/source/tombstone/knowledge-fact frontiers, knowledge-graph
generation, consumer-profile digest and host authority epoch.

This read-specific vector is intentionally narrower than
`LaneCGenerationVectorV1`. Prompt, compact, model, tokenizer, template and
tool-schema generations remain owned by their respective components and must be
bound at the boundaries that consume them; this adapter does not invent
defaults merely to make an authority receipt look complete.

The returned `LaneCAuthoritativeSnapshotProvider` is locked to the acquisition
request digest and can only return the already acquired snapshot envelope.
Agentd invokes `read_authoritative`; the lower-level `read_v2` projection is
not a crate-root product API. Before context return, Agentd fetches matching
content only when exact revision/content digests were admitted by the frozen
result, calls `revalidate_lane_c_snapshot`, constructs a fresh envelope from
the current owner cut, and calls `revalidate_authoritative_read`. The original
lease, request, provider, generation vector, snapshot, frontiers and receipt
bindings must all remain valid. StateControl additionally requires the same
fleet lifecycle authority epoch after asynchronous I/O.

Revalidation detects intervening corrections, deletions, newly appended source
evidence, projection changes, validity-time changes and host-epoch drift. It
rejects clock regression and expired leases. A write after the final check is
still possible: the API returns a historical read cut with bounded validity and
never grants a lease over future effects. These are crate-native APIs; no new
cross-module wire format or arbitrary caller-supplied generation vector is
authorized.

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
reopen, committed deletions, scope and verification/time filters, authoritative
provider binding, and restoration of an older valid SQLite backup. Agentd's
`cognitive_context_tests.rs` additionally injects source-frontier and tombstone
changes after an authoritative result is computed but before final consume-time
revalidation, proving fail-closed product composition. Run with
`just test -p codex-hepta-memory`.

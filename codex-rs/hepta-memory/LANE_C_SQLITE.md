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
graph generation are read in one SQLite transaction. The returned
`DurableCognitiveSnapshot` is an owned immutable cut; it is not a moving view
whose visibility and fetch methods can observe different current states.

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

`DurableCognitiveSnapshot::read(ReadRequestV2)` remains a lower-level owner-cut
projection primitive. It is useful to the owner crate and focused tests, but it
does not establish that the supplied historical cut is still the current
host-authoritative generation at delivery time. Product callers must not treat a
successful direct V2 projection as that stronger guarantee.

The `hepta-agentd` product path composes the cut through `bind_context` into an
`AuthoritativeCognitiveSnapshotProvider`, calls `read_authoritative`, and retains
the returned `AuthoritativeReadGuardV1`. Before delivery it reacquires a new
single-transaction owner cut, rebuilds the same host generation vector and calls
the guard's final-use revalidation. Exact provider identity, generation-vector
digest, snapshot digest, authority epoch, frontiers, receipt, deadline and lease
must remain valid. The surrounding Agentd state-control path passes its exact refreshed lifecycle
`current_generation` into the read, refreshes again after the async boundary,
requires Running+Ready and rejects any generation change, so lifecycle authority
cannot be replaced by a caller-supplied vector.

`revalidate_lane_c_snapshot` and `revalidate_lane_c_cut` remain owner-level exact
cut fences for store/recovery use. Product authoritative delivery uses the
broader provider/vector guard instead of relying on revision/current-cut equality
alone. A subsequent concurrent write after the final fence remains possible:
this read-only API never grants a lease over future effects.

`bind_context` binds an externally frozen `LaneCGenerationVectorV1`. All five
cognitive-owned components must exactly match the cut. The host supplies the
other profile/authority identities. In the Agentd context path, dimensions not
consumed by that path are bound to explicit domain-separated nonzero "not used"
identities rather than borrowed mutable ambient state; an optional learned
ranker contributes its independently pinned payload digest. Acquisition time
must match the observed second, and the owner adapter hard-bounds a lease to five
minutes; Agentd uses a stricter one-second context lease/deadline. These are
crate-native APIs and do not register V2 types as a cross-module wire format or
authorize arbitrary caller-supplied generation vectors.

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
binding, and restoration of an older valid SQLite backup. Agentd's `cognitive_context_tests.rs` additionally exercises the production
authoritative provider against real SQLite and requires final-use failure after
frontier, authority-epoch or lease drift. `cognitive_context_budget_tests.rs`
executes the full production `read()` path with a deterministic mid-flight owner
revision change and requires the delivery fence to fail closed. Run focused tests with
`just test -p codex-hepta-memory -p codex-hepta-cognitive-read -p codex-hepta-agentd`.

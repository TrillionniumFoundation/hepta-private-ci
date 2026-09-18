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
store. Agentd compares each fetched record's exact revision and content digest,
then calls `revalidate_lane_c_snapshot` before publishing the cognitive-context
response. Revalidation detects intervening corrections, deletions, newly
appended source evidence, projection changes, and changes caused by validity
time. It rejects clock regression.

For a later model effect, that Agentd response remains only a historical
observation. The native infer host retains the returned `snapshot_digest` and
`read_digest` and calls the owning Agent's `CognitiveContextFinalize` immediately
before `TurnStart`. The owner reacquires the same Agent-private Lane C scope,
requires exact snapshot-digest equality, reruns the same bounded V2 read,
requires exact read-receipt equality, and calls `revalidate_lane_c_snapshot`
again before returning success. Therefore a correction, deletion/tombstone,
validity change, citation/frontier change or restored older cut observed before
finalization makes the old context fail closed instead of reaching the model.

Neither API is a lock. A subsequent concurrent write remains possible after the
initial Agentd revalidation and also after a successful finalization response.
The Lane C API returns an observed historical cut and finalization returns a
newer observation; neither grants a lease over future effects. Atomic protection
past finalization would require a separately owned lease/revocation protocol and
must not be inferred from the digests themselves.

`bind_context` optionally binds an externally frozen
`LaneCGenerationVectorV1`. All five cognitive-owned components must exactly
match the cut. The host must obtain prompt, compact, model, retrieval-profile,
and authority values from their actual owners; the adapter supplies no defaults.
Acquisition time must match the observed second, and the lease field is bounded
to five minutes. These are crate-native qualification APIs; this change does not
register V2 types as a cross-module wire format or authorize arbitrary
caller-supplied generation vectors. The synchronous
`AuthoritativeCognitiveSnapshotProvider`/`read_authoritative` helper in
`hepta-cognitive-read` is not the production acquisition path; production uses
this durable cut plus explicit owner revalidation/finalization.

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
binding, and restoration of an older valid SQLite backup. Agentd's
`cognitive_context_tests.rs` additionally exercises the downstream race where a
context receipt is returned, its memory is tombstoned, and owner finalization of
the old receipt is rejected. Run the focused owner/read tests with
`just test -p codex-hepta-memory -p codex-hepta-cognitive-read -p codex-hepta-agentd`.
These commands name test targets; exact-candidate pass receipts are separate
qualification evidence.

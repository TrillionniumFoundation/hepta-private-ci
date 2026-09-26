# Lane C: the existing SQLite owner

`CognitiveStore::lane_c_snapshot` projects the existing `cognitive_1.sqlite3`
database into `hepta-cognitive-types::CognitiveSnapshot`. Existing memory/source
write APIs remain the only source-fact writers. The knowledge-graph integration
adds no second database, background synchronization, or replacement source
identity format; migration `0013_kg_generation_semantics.sql` adds immutable
canonical generation/publication receipts to this same SQLite owner. The
in-memory `hepta-cognitive-store` V2 implementation is not a durability backend.

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
| Verified, currently valid active head | Live `DURABLE_SQLITE_MEMORY_KIND` = `Fact`, content digest only |
| Provisional, expired, or future active head | Excluded from visible records |
| Committed tombstone | Tombstone, effective immediately even if future-dated |
| Ordered immutable revision chain | Canonical predecessor record digest |
| Number of scoped memory revisions / source rows / tombstones / fact sets | Corresponding owner frontiers |
| Scoped SQLite graph generation (zero when absent), plus canonical V2 generation digest when available | Graph generation plus one and digest-bound graph-read identity |
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

## Owner-bound retrieval observation

`CognitiveStore::observe_memory_retrieval` is the owner-side seam for the new
generation-bound retrieval engine. It executes the existing SQLite memory FTS,
entity FTS, graph one-hop and recency channels in one read transaction, before
legacy top-four truncation. Each owner channel is bounded to 32 observed rows and
reports whether that bound exhausted the query or was reached. The observation
retains every distinct revalidated candidate available inside those channel
limits, including candidates that the compatibility top-four API would omit.

Each observed candidate binds its exact memory revision, content hash, citation
source revisions/hashes, KG projection generation, reciprocal-rank score,
participating channels and the original per-channel rank. The observation
digest also binds channel saturation and the omitted final top-k count. It
contains no new write authority and does not assert complete recall beyond the
explicit owner channel limits.

`cognitive_retrieval_adapter` converts that observation into
`memory.retrieval` generator batches. The adapter does not accept caller-authored
source scores: normalized rank values are derived deterministically from the
owner-observed channel ranks, and generator receipts bind the owner observation,
Lane C generation vector and `Exhausted`/`LimitReached` state. Total
generation-bound input remains capped at 512 candidate events even when future
owners add channels.

The retrieval execution context additionally requires its
`RetrievalPolicyV1::digest()` to equal the Lane C
`retrieval_profile_digest`. This prevents a current SQLite cut from being
combined with a different retrieval policy while retaining the old generation
identity. Actual vector, causal, procedural and contradiction-support batches
must come from their own current owners; the SQLite adapter does not fabricate
them.

`bind_context` optionally binds an externally frozen
`LaneCGenerationVectorV1`. All five cognitive-owned components must exactly
match the cut. The host must obtain prompt, compact, model, retrieval-profile,
and authority values from their actual owners; the adapter supplies no defaults.
Acquisition time must match the observed second, and the lease is bounded to
five minutes. These are crate-native APIs. `read_ids_v1` is the typed-local ModulePort shape;
its canonical bytes and the V2 canonical bytes are not cross-process wire
protocols. Arbitrary caller-supplied generation vectors remain unauthorized.

Knowledge-graph materialization in `refresh_scope_projection_tx` derives one canonical
`hepta-kg` V2 generation from the exact current cognitive source cut, validates its
predecessor-bound publication, persists physical rows and semantic receipts, and only
then CAS-advances the current generation in the same transaction. GraphOneHop reads
reconstruct that generation, fence it by the persisted generation digest, and delegate
relation selection and temporal visibility to `hepta_kg::query_relations`; SQLite only
maps selected support identities back to physical memory occurrences.

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
heads (512-revision batches, at most 16,384 citations per batch, and
262,144 total ancestry revisions/citations of work per page). Its continuation
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

`cognitive_kg_oracle_tests.rs` additionally verifies full/incremental canonical V2 equivalence against SQLite, persisted physical/canonical digests, reopen, visibility, correction and tombstone; store tamper cases reject invalid canonical generation/publication receipts.

## Production use ordering and result observation

`ProductionAuthorityVerifier::enter_use` rejects by default. A trusted verifier
must supply a revocation-linearized owned guard. Semantic mutation acquires it
after `BEGIN IMMEDIATE`, validates the local lease in that transaction, and keeps
it until the cancellation-safe commit task finishes. Recovery keeps the guard
through private-copy verification and active publication and rechecks expiry
before publication. Revocation acknowledgement waits for prior holds.

`ProductionDurableWriter::cognitive_mutation_result` observes one exact original
operation without re-execution, including after lease release under the retained
identity/fence rules. Identical semantic retries yield typed `ObservedResult`.
The result exposes committed revision/digest metadata, not a new full-payload
write receipt or execution grant. Independent current-witness coordination and
authenticated recoverable archives remain distinct, unfinished host/owner work.

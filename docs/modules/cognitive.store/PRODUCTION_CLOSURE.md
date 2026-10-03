# cognitive.store production convergence

Status: source implementation and product composition exist. Candidate
qualification and declared module completion require evidence for their
applicable scopes. External bootstrap, independent acceptance, activation and
production execution remain separate states.

## 1. Ownership and the compiled product route

`codex-hepta-cognitive-store` owns the public cognitive module surface.
`durable.rs` re-exports `hepta-memory::CognitiveStore` as `DurableCognitiveStore`;
`hepta-memory` owns the single SQLite implementation and migration history.
This façade creates no second database, writer or authority.

The compiled product route is:

1. `AgentdProductionWriterHost::open_with_recovery` consumes an independently
   authenticated exact current-cut witness and an external authority verifier.
2. `DurableCognitiveStore::open_with_recovery` recovers a private SQLite
   generation while retaining the exclusive store fence.
3. `ProductionDurableWriter::open_with_live_verifier` retains the verifier and
   binds the writer to the same recovered generation, Agent, lease and epochs.
4. `ProductionCognitiveMutationCapability` exposes remember, correct and forget
   to Agentd and the memory extension, with authority and operation provenance
   in the same semantic transaction.

ExactCurrentCut recovery authenticates and preserves the complete supplied cut before writer acquisition. When acquisition creates a missing host-bound ACTIVE lease, its append to `cognitive_local_leases` legitimately changes the complete anchor's state digest; owner, profile and schema remain equal. Those identity comparisons after acquisition do not weaken the exact recovery witness requirement. A wrong full state digest must reject without changing the original cut, and the complete anchor after semantic work and writer release must equal ordinary reopen. The host's independent witness must track later durable writes. [Product integration fixtures](../../../codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs) distinguish these boundaries without changing authority, live-clock, TTL or activation gates; fixture source defines the boundary exercised; actual exact-candidate records establish execution and outcome.

The earlier `ProductionCognitiveStore` wrapper and its tests were outside the
Rust module graph and had obsolete recovery signatures. They are explicitly marked historical;
use the compiled route above. The raw compatibility constructor is available
only with `qualification-cognitive-write`; it does not provide a production
semantic mutation capability.

The operative interfaces and lifetimes are:

| Entry | Required input | Retained resource / rejection behavior |
|---|---|---|
| `AgentdProductionWriterHost::open_with_recovery` | `AgentdConfig`, recovery requirement, authority lease, `Arc<dyn ProductionAuthorityVerifier>`, lease ID/generation | Recovered owner, exclusive store fence, live verifier and sealed capability; recovery failure has no legacy-open fallback. |
| `DurableCognitiveStore::open` | Agent layout | Ordinary shared open guard and SQLite pool; unauthenticated read/bootstrap route. |
| `ProductionCognitiveMutation::{remember_with_kg,correct_with_kg,forget_with_kg}` | Scoped access, immutable source, draft/CAS predecessor | One SQLite write transaction; stale predecessor or authority denial rejects both semantic mutation and operation provenance. |
| `lane_c_snapshot_page` | Access/scope, time, bounded head limit and optional exact cursor | Read transaction and complete selected ancestry; changed owner cut rejects continuation. |

The embedding owns issuer provisioning, current revocation delivery and the
independent current-cut witness. It must refresh the retained witness after
settled mutations using an authenticated external process. A database-generated
anchor alone cannot prove external currentness.

## 2. Durable authority and transaction boundaries

The append-only `memory_revisions` ledger, citations and current-head projection
own memory history. `kg_revision_fact_sets`, `kg_revision_entities` and
`kg_revision_relations` own knowledge facts bound to that memory revision.
Semantic V2 images and canonical MemoryEvent shadow receipts are qualification
representations; they are not a second durable authority or a signed current-cut
witness.

A production semantic mutation requires:

- an external grant for the exact Agent, owner epoch, authority epoch and token;
- the process-lifetime writer lock and current durable lease generation;
- a retained live verifier checked before lock acquisition, after acquiring the
  SQLite write transaction and immediately before commit;
- atomic operation provenance and the memory/KG revision CAS in that transaction.

The 32 growing owner commit sites re-admit final uncommitted state in their own SQLite transaction. [Commit admission](../../../codex-rs/hepta-memory/src/cognitive_store_budget.rs) authenticates the exact compiled schema and applies the startup budget of 128 MiB logical values, 262,144 aggregate rows and 2 MiB per row to logical owner tables, logical FTS contents, `_sqlx_migrations` and the catalog. FTS shadow definitions are authenticated, while their physical contents remain excluded from the logical budget. Rejection discards every write in the transaction, including sealed production composites and their provenance. Remember/correct/forget finish with budget-admission await, synchronous `verify_retained_authority`, then `COMMIT`; the authority check follows the potentially lengthy admission scan.

The [immutable budget plan](../../../codex-rs/hepta-memory/src/cognitive_store_budget_plan.rs) uses a `OnceCell` of SQL derived from the fresh in-memory compiled 0019 table/column layout. No owner data, verified owner cut or usage counter is cached. Every growing commit first checks the complete owner schema in its own transaction, then scans all real logical rows for `COUNT`/`SUM`/`MAX`, with `LIMIT remaining_rows + 1` before aggregation. Types and NOT NULL declarations affect only actual-type `CASE` branch order; all framing, capacity limits and rollback rules remain unchanged. Startup, historical-prefix and journal admission retain their generic budget path.

Complete catalog verification preserves the typed, checksum-bound migration chain and original catalog count/byte bounds in that same transaction. Field byte lengths are individually NULL-safe, so a malformed NULL name/type/table cannot hide oversized SQL; small malformed NULLs still receive the typed refusal. Its immutable `OnceCell<Option<Arc<str>>>` scalar query comes only from quoted fresh compiled-reference literals. Three conditions jointly establish exact multiset equality: `BTreeSet` validates unique compiled reference names, the actual count equals the complete reference length in the same transaction, and `reference EXCEPT actual` is empty over all `(name, type, tbl_name, sql)` fields. The current reference has 188 rows including FTS shadows and NULL-SQL autoindexes. Each unique reference row must occur once with no extras; this is not a generic subset admission. Count alone misses duplicate/missing pairs and containment alone permits duplicate/extra rows. The actual catalog is fully scanned each cut; only Rust row materialization and the redundant comparison direction are reduced. Mismatch keeps the original bounded typed fetch/compare and errors, and future rendered SQL larger than 1 MiB uses that generic fallback. No owner data, usage or verified cut is cached.

Live-clock operation claims, renewals and effect-entry transitions resolve real time after `BEGIN IMMEDIATE`, operation-fence and claim-head reads. Claim, renewal and `Entered` enforce the persisted long writer deadline at that serialized cut; short operation TTL and retry-eligibility decisions use the same time, and renewal or `Entered` cannot revive an expired claim. Lock waiting cannot preserve stale admission time. Explicit `*_at` APIs retain their caller-supplied deterministic-time contract; that time is not evidence of current real-world authorization. Neither clock mode permits tolerance or clamping to bypass rollback/expiry checks, or adds authority. Settled markers retain the active owner generation/token requirement without newly rejecting wall expiry, so previously entered work can converge.

Final-use nonce persistence can outlast either deadline. After persistence, dispatch performs the retained-verifier precheck before final live-grant verification, then checks the writer deadline and short claim TTL immediately before actual target entry with no intervening await. Running the external retained verifier earlier prevents its latency or grant revocation from invalidating an already checked grant. A failed entry does not refund the consumed nonce; retry still needs a new independently authorized grant and reconciliation of unknown work. Current `AuthorityLease` and live-grant checks remain required, and exact-candidate lock-wait and actual-entry regressions are qualification evidence, not an execution claim in this document.

Budget or authority denial before a semantic mutation's commit rolls back its entire semantic transaction.
The external verifier must provide current revocation semantics; source code
cannot manufacture those semantics or atomically freeze an external authority.

### Public terminal receipt contract

`ProductionDispatchReceipt.target_receipt` and `target_reason` preserve the actual
destination reply. `local_event_id` names the verified durable local event; it
does not assert that this event persisted the returned transport payload. New
observer-settlement events use the `observed-event:` ID namespace, with the
corresponding `reconcile_committed`, `reconcile_rejected` or
`reconcile_still_indeterminate` kind and canonical outcome payload. Normal ACK
and generic apply/reject events retain the `event:` namespace.

A matching normal ACK may reuse a previously persisted observer terminal event
despite a different transport payload only after verifying that new observer
origin, matching terminal kind/canonical outcome and the same current fence.
Opposite terminal results, stale authority/fences and different actual ACK
replays remain errors. Legacy `event:` history remains readable, but a literal
`committed` or `rejected` payload cannot establish observer origin and receives
no different-ACK exception. Exact-payload replay retains its normal idempotence.

The observer settlement stores the terminal classification, not its raw observed
receipt or reason. The returned transport fields and the durable event must
therefore be interpreted separately. Reconciliation observes existing work and
never redispatches it; a missing source row remains unresolved rather than proving
that an in-flight mutation cannot commit. For `ProductionCognitiveMutationReceiptV1`,
public digest/validation checks establish consistency, while producer
authentication and retained owner evidence establish receipt provenance. Neither
receipt form creates execution authority.

## 3. Reopen and rollback-sensitive recovery

Ordinary `DurableCognitiveStore::open` is the bounded read/bootstrap path. It
checks database and existing sidecar identities before SQLite access and verifies
the compiled owner schema and migration-ledger schema before relying on CHECK constraints
or integrity queries. Before pending migrations execute, bounded migration rows
must identify a continuous compiled history prefix whose complete schema matches
a separate in-memory reference built from the compiled migrations. After this
schema admission and before `MIGRATOR` executes, any existing `cognitive_meta` row
receives bounded type and owner validation against `layout.agent_id()`. New
databases can initialize, and missing metadata is accepted only for a genuinely
empty logical application state. Existing local owner columns and operation
subjects are checked before migration; orphan and foreign-owned state are denied
without advancing the migration prefix. The same snapshot enforces logical row
and byte admission before materialization. This
preserves clean historical upgrades while rejecting altered triggers, CHECKs,
autoindexes and FTS shadow definitions. When initialization or upgrade is needed,
prefix admission, existing-owner validation, compiled migrations, full-schema
verification and owner metadata initialization share one `BEGIN IMMEDIATE`
transaction. The completed schema is verified again
in the same transaction as integrity scans. Independent content, projection and
journal verifiers admit their own exact snapshots before reading executable
schema or materializing history. It recomputes source and memory digests in bounded batches and
checks exact historical Memory FTS membership/content plus FTS5 integrity.
Expired and tombstoned revisions remain in that historical index and are filtered
by owner read semantics. Existing files with unsafe mode are rejected rather
than automatically chmodded; operators must establish trusted private-file
ownership before reopen. Ordinary path-based pooling does not guarantee safety
against continuous same-UID pathname replacement. It does not authenticate a database against an external current
cut and is not the production writer recovery route.

Owner admission first reads the fixed SQLite header scalar `PRAGMA encoding` and accepts only `UTF-8`, in the existing `BEGIN IMMEDIATE` transaction. This read does not evaluate owner-defined SQL and precedes SQLx/schema text byte-bounds, exact historical schema admission, budget, owner checks and migrations. A matching UTF-16 historical schema is refused even with empty application tables; silently converting its text bytes would change the canonical Memory contract and metadata byte limits. The historical encoding-denial fixture preserves the complete predecessor image and cold bytes.

The private `MigrationAdmission::AlreadyCurrentOwned` result applies only after a complete successful current migration prefix through 0019, exact schema, global budget, all local-owner checks and one valid matching metadata singleton. `open` rolls back the initial fence and skips migration, metadata insertion and the redundant initialization commit. The unchanged `verify_store` path then independently admits fresh transaction cuts and performs canonical stable-ledger SHA verification once, without reusing the earlier proof. This is no production authority or independent current-cut witness. [Current refusal cases](../../../codex-rs/hepta-memory/src/cognitive_store_schema_ownership_tests.rs) preserve full images and cold bytes for corrupt Source content and for empty metadata with corrupt physical FTS despite zero logical FTS rows.

Whenever initialization or upgrade is needed for a compiled prefix greater than zero, bounded stable-ledger verification runs after schema, budget and all existing-owner checks and before `MIGRATOR`, inside their same write transaction. Historical prefixes and current stores with empty metadata retain these checks. It recomputes Source/Memory canonical content digests, requires every retained Memory identity's current head to identify its latest revision, requires 1–32 citations per revision with contiguous zero-based ordinals and exact source owner/scope equality, and checks exact Memory FTS membership/content and inverted-index integrity against tables stable since migration 0001. Clean prefixes remain upgradeable; known corruption rejects before migration 0003 can erase old KG evidence. The [real-v2 historical corruption matrix](../../../codex-rs/hepta-memory/src/cognitive_store_schema_ownership_tests.rs) compares complete schema, SQLx history, owner, Source/Memory/citations, generation-7 KG and cold source after denial, including missing heads and heads rolled back behind retained history. This historical admission does not establish complete semantic integrity of arbitrary historical KG state or a successful test result.

Stable typed metadata is byte-bounded before 64-row pages, then parsed with the scope, source-kind, verification, lifecycle, digest and ID contracts, including legacy `memory:v1:` compatibility. Workspace digests require all 64 lowercase hexadecimal bytes; tombstone reasons must be nonblank under Unicode `trim()` and at most 256 UTF-8 bytes. Memory content requires valid UTF-8 while Source content remains arbitrary bytes. NULL-safe predecessor/scope checks reject missing predecessors, scope changes and tombstone resurrection. TEXT ID/content and INTEGER revision checks make exact Memory FTS membership resistant to type aliases. These checks close SQLite CHECK NULL semantics without adding authority or tightening legitimate historical identity formats; a companion positive fixture covers valid two-revision `memory:v1:` upgrade and reopen.

Public `StableMemoryId::parse` preserves both exact v1/v2 prefixes with precisely 64 lowercase hexadecimal bytes and rejects other versions or malformed digests. New IDs continue to use v2 hashing; migrated v1 IDs remain unchanged through reads, ranked retrieval, correction, source explanation and reopen. [Public legacy regressions](../../../codex-rs/hepta-memory/src/cognitive_model_legacy_tests.rs) cover the actual historical fixture, current-head FTS filtering, negative grammar and new v2 creation. This compatibility changes neither authority nor stored identity.

The needs-initialization path applies `SELECT 1 FROM pragma_foreign_key_check LIMIT 1` after exact schema, full-budget and owner checks, before stable-ledger verification in that transaction. Any violation refuses migration with bounded violation-presence output. After the stable-ledger checks, `PRAGMA quick_check(1)` must return exactly the single value `ok` before pending migrations execute. The dangling-source-citation, orphan-Memory-head, invalid CHECK validity-range and same-owner cross-workspace citation cases compare the full historical image and unchanged cold bytes, including old KG evidence that migration 0003 would delete. These checks supply neither arbitrary historical KG semantic validation nor a current-cut authenticity proof.

[Migration 0016](../../../codex-rs/hepta-memory/migrations/0016_memory_citations_source_lookup.sql) adds the covering reverse-citation index on `(source_id, source_revision)`.

[Migration 0017](../../../codex-rs/hepta-memory/migrations/0017_kg_storage_count_admission.sql) replaces the generation-storage count trigger. Each node/edge count uses zero only when its actual immutable fact table is empty; a declared zero receipt is not a shortcut. Otherwise scoped identities are deduplicated at or before the requested generation, their latest historical triggers are selected by indexed `MAX(generation)`, and the original verified/active Memory filters count revision facts. Matching receipt/semantics scope and generation remain mandatory, without substituting current heads.

[Migration 0018](../../../codex-rs/hepta-memory/migrations/0018_memory_revisions_scope_frontier.sql) adds the covering index on `(owner_agent_id, scope_kind, workspace_sha256, lifecycle, memory_id, revision)` for retained Memory frontiers. The existing aggregate SQL and its owner/scope, lifecycle/history and fact-receipt semantics are unchanged.

[Migration 0019](../../../codex-rs/hepta-memory/migrations/0019_source_ledger_scope_frontier.sql) adds the ordinary, non-unique covering index on `source_ledger(owner_agent_id, scope_kind, workspace_sha256, source_id, source_revision)`. The KG cited-Source `COUNT` SQL keeps its owner/scope/workspace predicates and exact citation `EXISTS`, without reading payloads for those covered fields. Uncited appends still do not advance the graph frontier; the broader Lane-C cut independently fences every Source change. The compiled oracle for 131 required schema objects is `daba235025b667251c5d6b5500db5ab8b0096f32c5bc0222ef78ec2b88026f5c`, distinct from the complete 188-row catalog reference. Semantic digest algorithms and binding scope are unchanged; native execution and performance claims require actual exact-candidate records. Migration definitions and SQL models alone do not supply them.

Writable recovery is implemented in `cognitive_store_recovery.rs`. It retains
source database/WAL/journal descriptors, copies them to a private generation,
checks the exact independent anchor and integrity, checkpoints the copy, and
publishes its active pointer atomically. Source files remain untouched. Source
descriptor identity is revalidated during materialization while the exclusive
store fence remains held. The publication boundary rechecks the exclusive fence,
external authority and local lease expiry; it does not perform a new source
descriptor capture. Rejection leaves the old active pointer in place.

The old `codex-state` recovery-writer API returning `Unavailable` is not this
route. Platform inability to supply required identity/locking guarantees still
fails closed. Recovery does not grant authority to repair a corrupt ledger,
accept a stale witness or restore a forgotten revision.

## 4. Cutover and rollback procedure

No dual write or second database migration is required. Stop new writes, drain
and reconcile outstanding work to a recorded watermark, release the old writer,
and retain an independently authenticated current-cut witness. Validate schema,
revision lineage, citations, tombstones and KG fact counts. Recover through the
product host using a fresh external lease and generation; compare the pre-write
cut before a canary mutation. Retain exact candidate and merge verification
receipts before publishing the new route.

Rollback follows the same procedure with a compatible binary and a fresh lease.
Never reuse an old fence or restore a backup without an independent current-cut
witness. Incompatible schema or an unverifiable current cut stops rollback.

## 5. Qualification and remaining completion gates

Ordinary authorized source development uses affected package tests and
`python3 scripts/hepta-docs.py verify --profile development` against the current
working tree. It does not require handwritten runtime receipts merely to edit,
test or merge source. Explicit `--profile qualification` checks retain committed
candidate identities and the evidence required by the exercised boundary. A
development-profile pass does not establish runtime execution or acceptance;
the production-writer lease, live verifier and independent current-cut witness
remain mandatory host inputs.

Run package tests for `codex-hepta-cognitive-store` and `codex-hepta-memory`, plus
Agentd product writer/composition tests. Cover lock contention with revocation,
precommit denial, exact-cut recovery, hostile database/sidecar identities,
correction CAS, non-resurrection and rollback. Run scoped Clippy, formatting,
caller proof and module-document/implementation-map checks against the exact
candidate. Test invocations are not pass receipts.

Current source regressions include [owner-budget and sealed production rollback](../../../codex-rs/hepta-memory/src/cognitive_store_budget_tests.rs), [real lock-wait and final-use entry clock cases](../../../codex-rs/hepta-memory/src/production_operation_claim_clock_tests.rs), and the [compact](../../../codex-rs/hepta-memory/src/local_compact_executor_capacity_tests.rs), [lease](../../../codex-rs/hepta-memory/src/local_lease_outbox_capacity_tests.rs) and [logical-turn registry](../../../codex-rs/hepta-memory/src/logical_turn_registry_capacity_tests.rs) capacity cases. These source references identify regression scope; execution claims belong to actual records bound to the tested candidate.

[Budget-plan expression cases](../../../codex-rs/hepta-memory/src/cognitive_store_budget_plan_tests.rs) compare generic framing against declared-type/NOT NULL branch hints for every actual storage class, Unicode/NUL, invalid UTF-8 TEXT and byte-ceiling-sized values. The [public legacy cases](../../../codex-rs/hepta-memory/src/cognitive_model_legacy_tests.rs) exercise migration and public operations, rather than only private integrity decoding. Their source presence is not an execution pass.

[Head-digest cases](../../../codex-rs/hepta-memory/src/cognitive_kg_head_digest_tests.rs) compare checked borrowed SQLite rows with the independent reference digest for 0/1/512 heads, reject malformed receipts and actual types, and exercise public correction/reopen across scopes. The ordinary [nextest configuration](../../../codex-rs/.config/nextest.toml) serializes the real Source-budget and memory `capacity_tests::` fixtures in the existing `hepta_durable_capacity` group, with one thread. An exact-name, package-limited override gives only the full 128 MiB `legal_source_appends_stop_atomically_at_reopen_budget_and_replay_at_capacity` fixture `threads-required = 'num-test-threads'`, excluding ordinary tests from competing for slots in that invocation. This is no isolation from unrelated processes or latency qualification. Default 60-second watchdog, one retry, complete caps/payloads and the separate 1,200-second maximum-profile deadline remain unchanged.

[Catalog cases](../../../codex-rs/hepta-memory/src/cognitive_store_schema_catalog_tests.rs) compare scalar equality with the complete typed reference, including FTS shadows and NULL-SQL autoindexes; they reject data-only catalog variants, duplicates and over-budget metadata. They identify validation scope and do not claim a native execution result.

Retained local owner evidence for clean `1276b1f4f75e1903bb240f09abe044ae880c5a42` / tree `b25a42b27fb36eb5c259b7a17090bcb31a2e074f` recorded 419 passed tests and 7 skipped; its actual log includes the catalog fault matrix and cited-Source-frontier regression. This is a fixed result for that candidate, not a claim about a later documentation/source head, maximum-profile latency, product/state integration or independent production acceptance. Those scopes require their own actual candidate-bound records.

The `126c6f87ae2a05e825c86cec9c62ab6cc0e69ed5` source-head architecture run passed 32 selected Agentd library tests but failed its one product-writer fixture at the old pre/post writer-acquisition anchor comparison; state SQLite recovery therefore did not execute in that step. The corrected fixture requires exact bad-cut refusal and unchanged original state, separates the legal ACTIVE lease append from recovery equality, and compares the complete post-release anchor with ordinary reopen. Retain each candidate's actual product-integration and state-recovery records. A preceding library pass does not prove either scope, and old results are not transferred.

The [technical guide's integration/recovery commands](TECHNICAL.md#12-verification-and-qualification)
select Agentd `cognitive_` / `production_writer_host` library tests and state
`sqlite_recovery` library tests
with an empty-test failure policy. Architecture convergence configures them in
its source-head/base-merge lanes under the existing native-execution and
effects/learning/lifecycle selection conditions, retaining command records or
an exact-tree reuse decision. Their addition is not a successful execution
receipt and does not replace Agentd product-host integration qualification.

The focused native owner workflow runs strict Clippy for
`codex-hepta-cognitive-store` and `codex-hepta-memory` with `--no-deps` and
`-D warnings`. It compiles dependencies while limiting lint qualification to
these two owner crates. Whole-repository and Agentd qualification remain
separate gates. Crash/reopen and both configured performance profiles require
their own successful exact-run receipts; workflow definitions are not results.

The registry records `production_implementation=false`. Source presence, named
composition and scoped test results do not themselves change that field or
establish external acceptance, activation or release. The repository does
not provision the external issuer, authenticated current-cut witness service or
operator acceptance; those remain independent host lifecycle obligations.

Per-chain ingress preserves compact and lease ceilings of 4,096 rows and the registry ceiling of 16,384. Compact's shared insert boundary also protects direct atomic rehydration witnesses; exact replay does not require a new slot. A near-limit registry takeover whose second append exceeds the ceiling rolls back the superseded marker, old-lease rollback and new successor lease together. H7's 16,384-row guard is defensive consistency only: its current legal start/terminal state machine has at most two rows, so no 16,385-row legal-chain failure is claimed.

Full actual-catalog and logical-state scans run on every growing commit, with no usage cache. Successful complete-schema comparison can use a SQLite set scan rather than Rust full-row fetching; logical `COUNT`/`SUM`/`MAX` still read actual owner state in the same transaction. Logical framing remains NULL 16 bytes, integer/real 64 bytes and Text/Blob `24 + octet_length(column)`; replacing cast-based byte length preserves the budget while avoiding large payload reads merely to obtain stored lengths. A pinned SQLite 3.51 model found equivalent old/new accounting for 24 typed values within each of UTF-8, UTF-16LE and UTF-16BE; these probes do not expand UTF-8-only owner admission. Its warm isolated Source aggregate over 126 × 1 MiB contents measured 24.939→0.199 ms, and the unchanged frontier SQL over 16,384 revisions/512 heads measured 24.984→10.241 ms with the 0018 index. These historical SQL-only scratch-model medians used an optimization-level-2 SQLite C engine, excluding Rust/SQLx, complete admission, synchronization, concurrency and deadline qualification. They supply no native, release or deployment performance pass. The ordinary dev/test [package overrides](../../../codex-rs/Cargo.toml) now apply optimization level 3 to `libsqlite3-sys` for all profile consumers; owner Rust level 0, release level 3, checks, caps, benchmark payloads and deadlines remain unchanged.

The immutable compiled query plan avoids repeated budget layout discovery and aggregation SQL rendering while retaining full schema authentication and real row scans. An exploratory local maximum-retained run using the optimization-level-2 SQLite build and migration 0018 exceeded the unchanged 1,200-second deadline. For clean `126c6f87ae2a05e825c86cec9c62ab6cc0e69ed5`, its default-profile local maximum run failed at 1,200.072578 seconds with last progress at 13,824 of 16,384 revisions; its GitHub source-head maximum run failed at 1,200.064049 seconds with last progress at 13,312. These remain separate actual failures, not transferred timing/progress. Neither is a qualification pass or evidence for subsequent source. Every changed source/build-profile candidate requires its own actual native records for the selected workload, deadline and integration scopes; earlier evidence is not transferred.

The projection head query keeps `memory_heads` first with `CROSS JOIN memory_revisions` and the same ID/revision join condition, preserving returned fields, owner/scope predicates, declared/actual fact counts, `h.memory_id` order and `LIMIT`. The 512-head/16,384-revision SQL-only model reduced SQLite VM instructions by about 83%; this is no native performance pass and does not guarantee improvement with many other-scope heads. The builder hashes checked borrowed row fields with the original domain/scope/count/six-field framing, rejects missing receipts, count drift and invalid fact digests, and drops rows before its next await. Fact-digest validation still allocates; independent reopen retains the original reference decoding and digest semantics.

The separate historical 0018 SQL-only catalog model reduced warm execution from 1.158 to 0.576 ms and output from 187 rows to one. Its 77,402-byte scalar SQL increased preparation from 0.021 to 0.880 ms, measured separately. These Python C-API observations do not establish SQLx/native savings, a deadline pass or production performance.

A separate O2/O3 SQL-only model used identical SQLite 3.51.3 source identity and compile-option macros over the read-only older SQLx 0017 plus `18_model` fixture. Its 32 budget table queries retained identical 131,790 rows, 115,892,874 logical bytes, maximum row size 5,107 bytes and 8,722,041 VM instructions. CPU decreased from 333.512 to 278.907 ms, about 16.4%, and wall time from 1,500.249 to 1,285.472 ms amid substantial host contention. Another isolated catalog model measured the three-condition single-direction proof at 0.3763 ms/3,784 VM instructions versus 0.7953 ms/6,248 for two directions. Neither measures full native admission or qualifies the deadline. The 13-variant data-only catalog matrix is one parameterized source test, including same-count duplicate/missing rejection and parity with the original typed vector oracle; the native command record binds execution and outcome to the tested candidate without certifying performance or production acceptance.

A cited-Source-frontier SQL-only model used an older SQLx 0017 fixture and an equivalent experimental `18_model` covering index, preserving the existing owner/scope and citation `EXISTS` result of 16,384. VM instructions decreased from 213,008 to 131,090, wall time from 28.002 to 9.616 ms and CPU time from 20.747 to 7.552 ms. This models the index, not native compiled-0019 admission or maximum-profile qualification. A separate flattened `UNION ALL` budget model showed slight regression and was not implemented; per-table full actual-state scans remain in force.

Bounded state is not a latency qualification. Global terminal capacity has no reserved budget. ACK, reconcile, revoke or lease-finalize may reject near global exhaustion while preserving the previously admitted, reopenable cut. That preserves recoverability without promising terminal progress. Shared-experience revision 1,025 is only a policy-local revocation reserve and does not guarantee withdrawal under the global owner budget. Authoritative append-only history remains retained without a new long-term retention or garbage-collection policy. Capacity reservation, overload behavior and performance remain selected-host completion conditions.

Agentd context admission, publication and final-use now use bounded exact-ID
snapshots. Candidate and output selections share a global owner witness covering
all head identities, content, visibility and source/fact/tombstone frontiers;
only selected complete ancestry/citations are materialized. Unrelated accumulated
history therefore does not consume the selected ancestry budget. Each request
still enforces 512 IDs, 16,384 ancestry revisions and 65,536 citations; overflow
is an error. Global witness construction scans retained heads with bounded RAM,
so latency still grows with scope size. This witness depends on immutable ledger
semantics and never replaces the independent full-database recovery anchor.

Reconciliation uses destination-local shared cursors and a frozen semantic
preparation-sequence upper bound per scan cycle. Wall-clock preparation timestamps
and operation IDs are not the admission watermark. Unresolved early rows and
continuing new arrivals cannot prevent prior rows from being revisited. The cursor
resets on writer restart and carries no durable authority. The Agentd host also
rotates across at most 256 destinations through a clone-shared cursor. Concurrent
normal ACK and reconciliation settle only verified matching terminal outcomes;
the public terminal receipt contract above defines the new observer-origin
exception without weakening actual ACK replay checks. Opposite results and
stale fences remain errors. A missing source row remains unresolved until a trusted
terminal observation exists. Cross-cache forget settlement, physical erasure and
canonical shadow promotion also require their own evidence.

Publication and final-use check the full owner witness after their last internal
await. Learning records created before a response returns contain assignment
facts only, with no delivered candidates, exposure claim or published digest.
A successful return is not a consumer acknowledgement.

Cold read-only recovery follows the validated active-generation pointer, and
nonregular pointers are rejected without a blocking FIFO open. Failed recovery
copy writes or syncs remove only files created by that attempt; pre-existing
collision files remain intact.

## 6. Claim vocabulary

- **Source implemented:** compiled entrypoints and invariants exist.
- **Product composed:** the named Agentd host uses the recovered owner and sealed
  mutation capability.
- **Candidate verified:** exact execution receipts demonstrate the tested scope.
- **Production accepted / activated / released:** independently established host
  lifecycle states, never inferred from source or qualification fixtures.

## 7. Adversarial audit scope

The 2026-10-01 audit covers semantic V1/V2, durable SQLite, recovery, production
authority, terminal observation and Agentd context composition. Regression cases
cover forged commit/receipt cuts, deletion reserves on smaller reopen, snapshot
frontier/lineage drift, cross-page tombstone resurrection, canonical UTF-8 reason
hashes, database/sidecar aliases, content/FTS tampering, recovery/write-lock
revocation, create-only predecessor drift, delayed target commits, single-cut
observation, fair reconciliation and bounded selected reads beyond 16,384 total
revisions. Follow-up cases include orphan/foreign-owner historical admission,
concurrent DDL between admission and integrity, startup journal budgets,
late-await cut drift and truthful learning assignments, destination fairness,
both ACK/observer race orders, active-generation cold reads and failed-copy
cleanup. Fixes receive independent follow-up source review.

V2 image and page digests establish consistency, not source authenticity or
freshness. Single-page validation proves only available ancestry; consumers
validating successive untrusted pages use `validate_continuation` to retain the
preceding tombstone boundary. The authentic owner also checks continuations
against its ledger. Ordinary path-based pooling does not resist continuous
same-UID pathname replacement. External revocation and SQLite COMMIT have no
shared linearization protocol; the last authority check precedes COMMIT.

Record actual test/format/lint/performance results against the candidate before
calling it verified. Independently supplied production bootstrap, acceptance,
cache deletion settlement, retained-backup erasure and unlearning remain separate
gates. Source fixtures and internal checksums cannot manufacture these facts.

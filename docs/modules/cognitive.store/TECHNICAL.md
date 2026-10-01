# cognitive.store technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `cognitive.store`

**Owner:** `cognitive-platform`

**Deputy:** `durability-kernel`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `MEM-1-STORE`

This stable document is the implementation guide for `cognitive.store`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Own the Memory ledger and its memory-revision-bound authoritative knowledge-fact subledger with citation, correction, deletion and lineage semantics. Knowledge facts are committed with a specific Memory revision; they do not form a second independently writable fact-history authority.

The primary owner `cognitive-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `durability-kernel` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `store`, state model `stateful` and architecture role `authoritative_store` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-cognitive-store`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-cognitive-store`

Non-authoritative implementation evidence roots:

- `codex-rs/hepta-memory` (physical SQLite engine; the canonical module API remains in `hepta-cognitive-store`).

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The registered primary source is [codex-rs/hepta-cognitive-store/src/lib.rs](../../../codex-rs/hepta-cognitive-store/src/lib.rs). The semantic V2 surface includes `AdmittedCognitiveStoreV2`, exact-cut snapshot paging, and shadow-only canonical `MemoryEventV1` co-observation through `append_admitted_with_canonical_shadow`; the canonical production façade re-exports `DurableCognitiveStore` and production writer/recovery types from [durable.rs](../../../codex-rs/hepta-cognitive-store/src/durable.rs) without creating a second database. The physical implementation remains [hepta-memory::CognitiveStore](../../../codex-rs/hepta-memory/src/cognitive_store.rs), and the named product caller is [AgentdProductionWriterHost](../../../codex-rs/hepta-agentd/src/production_writer_host.rs). These are source bindings; exact-candidate execution, independent acceptance, activation and release remain separate evidence states.

## 3. Boundary, responsibilities and non-goals

Current durable integration: the physical memory/source writer remains the
existing SQLx `hepta-memory::CognitiveStore`. Its
`codex-rs/hepta-memory/src/lane_c_snapshot.rs` adapter projects one authorized
SQLite transaction into the new cognitive snapshot and read types; it does not
add a second writer or synchronize a second database. The in-memory V2 store in
this module is not a durable backend. See
`codex-rs/hepta-memory/LANE_C_SQLITE.md` for exact ID/frontier mapping, bounded
materialization, correction/deletion propagation, and reopen/rollback-witness
behavior. Writable `open_with_recovery` now uses retained file descriptors,
a shared/exclusive store fence, bounded database/WAL/journal copying into a fresh
private generation, exact current-cut comparison, SQLite integrity/checkpoint
verification, an externally verified production-authority fence, and atomic active-
generation publication. Ordinary `open` still has no independent current-cut
proof and must not be reported as equivalent recovery admission.

Direct dependencies:

- `cognitive.types`
- `kernel.operations`

Authoritative write domains:

- `memory_ledger`
- `knowledge_fact_ledger` — a memory-revision-bound fact-set subledger stored atomically with the owning Memory revision, not an independently writable second ledger

Explicitly denied capabilities:

- `federated_network_read`
- `model_call`
- `learning_policy_write`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `schema and migration owner`
- `transactional writer`
- `snapshot read port`
- `integrity and lineage verifier`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

### Shared experience target: publish through the existing owner

Extend the existing source/Memory owner with scoped contribution admission, not
another shared fact store. The physical source writer and Memory-revision-bound
fact subledger retain their current atomicity. Producer Agent identity, durable
shard identity, owner epoch, source revision, publication audience and training
purpose are distinct. The current AgentPrivate/WorkspacePrivate scope encoding is
unchanged; any new shared audience/export metadata needs registered versioned
contracts and migrations before product use. Do not erase AgentId from existing
stable IDs or reinterpret an old private scope as common data.

The target ingress validates exact policy/current source, content bounds, provenance,
allowed raw-read/training/derived-use scopes and expected predecessor before
idempotent admission. Store a permitted derived copy or a resolvable owner reference
with original lineage; that publication is not an independent corroboration. Export
intent and local state commit atomically where the existing owner permits; remote
apply/ack uses the existing cross-owner protocol, never a pretend multi-DB transaction.
Contribution attempts cannot replace another owner or open their writable file.

A share/read view may select many owner shards while each mutation has one fenced
writer. Stable shard data outlives a temporary Agent; retirement transfers/archives
it with current-cut and ownership evidence rather than copying an active SQLite/WAL
into a new identity. Snapshot references are bounded by count/bytes/frontier and
freshness. Incomplete, revoked, schema-incompatible and unreachable sources retain
explicit dispositions. Corrections and deletion flow to derived views/artifacts;
retained audit links never justify retaining prohibited payload. Full semantics:
[shared HNMF](../../hnmf/TECHNICAL.md#authorized-contribution-and-shared-view-publication).
These are planned extensions; current source/product states below remain unchanged.

### Implemented same-host shared-use subset

`CognitiveStore::{grant_shared_experience,read_shared_experience,
revalidate_shared_experience,revoke_shared_experience}` uses the existing SQLite
owner, exact Memory revision and separately bound Recall/Replay purposes.
Replay also binds parameter scope and artifact consumer. This is a local owner
API, not a new cross-host protocol or public Memory scope.

The immutable policy log permits 1024 ordinary revisions and reserved terminal
revision 1025. Renewal exhaustion cannot prevent withdrawal; the final slot cannot
contain an active grant. Repeated withdrawal and reopening preserve rejection.
`SharedExperienceUseV1::source_support_digest` binds owner, Memory identity,
revision and content: equal text in another record is not the same training source.
Permission and source currentness are checked again at consumer use. This subset
accepts current verified evidence, not general historical Replay eligibility.

Source: [shared_experience.rs](../../../codex-rs/hepta-memory/src/shared_experience.rs).
Tests: [shared_experience_tests.rs](../../../codex-rs/hepta-memory/src/shared_experience_tests.rs).
These tests do not establish OS isolation, cross-host enrollment or model unlearning.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::knowledge_fact_ledgerV1`
- `DomainRead::memory_ledgerV1`
- `ModulePort::cognitive.store::knowledge.graph`

Consumed contracts:

- `DomainRead::cross_owner_outboxV1`
- `DomainRead::operation_ledgerV1`
- `ModulePort::cognitive.types::cognitive.store`
- `ModulePort::kernel.operations::cognitive.store`
- `OperationIntentV1`

Critical protocol schemas:

None.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `knowledge_fact_ledger`
- `memory_ledger`

Read-only data dependencies:

- `cross_owner_outbox`
- `operation_ledger`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Production semantic mutations additionally bind the live authority grant digest, authority epoch, owner epoch, writer lease generation, semantic input digest, expected predecessor revision, authoritative source revision, and final write digest into the existing append-only local event/outbox journal. Admission, the source/Memory/fact/projection mutation, and the terminal committed provenance marker share one `BEGIN IMMEDIATE` transaction. A failure after admission but before semantic commit therefore rolls back the provenance rows together with the domain mutation; a successful production receipt is queryable as a terminal committed occurrence and carries no external-effect authority.

The 32 growing owner commit sites use [cognitive_store_budget.rs](../../../codex-rs/hepta-memory/src/cognitive_store_budget.rs) to admit their final uncommitted state against the startup limits: 128 MiB of logical values, 262,144 aggregate rows and 2 MiB per row. Admission authenticates the exact compiled schema in that same transaction, then counts the logical owner tables, logical FTS contents, `_sqlx_migrations` and the SQLite catalog. FTS shadow definitions are authenticated but their rebuildable physical contents are excluded from this logical budget. Failure rolls back the entire transaction, including sealed production source/Memory/fact/projection writes and operation provenance. The sealed remember/correct/forget composites finish with budget-admission await, synchronous `verify_retained_authority`, then `COMMIT`; no additional asynchronous work precedes that commit after the authority recheck.

Growing commits reuse the immutable plan in [cognitive_store_budget_plan.rs](../../../codex-rs/hepta-memory/src/cognitive_store_budget_plan.rs). Its `OnceCell<Vec<Arc<str>>>` retains aggregation SQL derived only from table/column metadata in a fresh, owner-free in-memory database migrated through the compiled 0019 schema. It caches neither owner data, verified owner cuts nor usage totals. Each commit first authenticates the complete owner schema in its own transaction, then executes every plan query against that transaction's real logical rows, computing `COUNT`, `SUM` and `MAX` with the input bounded by `LIMIT remaining_rows + 1`. The 128 MiB/262,144-row/2 MiB-row caps and rollback behavior are unchanged. Declared column types and NOT NULL flags only reorder `CASE typeof(column)` branches: all actual SQLite storage classes, including declaration violations and NULL, retain their existing byte framing. Startup, historical-prefix and journal-snapshot admission retain their generic schema-derived budget path.

Full catalog verification retains the complete typed, checksum-bound current migration chain and original catalog count/byte bounds in the same transaction. Each of the four metadata fields contributes its byte length with NULL treated as zero, so a NULL name/type/table cannot hide an oversized SQL field from the byte guard. Small malformed NULLs still reject under the typed comparison. For the current compiled schema, the complete catalog has 188 rows, including FTS shadow definitions and NULL-SQL autoindexes. A separate immutable `OnceCell<Option<Arc<str>>>` holds a query containing only quoted literals from the fresh compiled reference. Success requires three conditions together: the builder uses `BTreeSet` to prove every compiled reference name unique; the same transaction's actual catalog count equals the complete reference length, currently 188; and `reference EXCEPT actual` is empty over all `(name, type, tbl_name, sql)` fields. Each unique expected row must therefore occur once and no extra row can remain: this proves multiset equality, not a generic subset test. Count alone would permit a duplicate/missing pair, while containment alone would permit extras or duplicates. A matching catalog returns one scalar instead of copying all rows into Rust; the actual catalog is still fully scanned on every cut. Mismatch retains the original bounded typed fetch/compare and error classifications. If future rendered SQL exceeds 1 MiB, the optimization falls back to that generic path. No owner data, usage or verified schema cut is cached. [Catalog regressions](../../../codex-rs/hepta-memory/src/cognitive_store_schema_catalog_tests.rs) cover complete reference parity and a 13-variant data-only fault matrix, including identical duplicates and same-count duplicate/missing pairs, plus byte-bound refusal with NULL fields beside oversized SQL. The variants are one parameterized matrix, not 13 independently executed tests.

`ProductionCognitiveMutationReceiptV1::validate` and its receipt digest check consistency of public fields; they do not authenticate the producer, independently prove currentness or prove that a mutation committed. Receipt consumers crossing a trust boundary must authenticate the producer and correlate the referenced event/outbox/write with retained owner evidence. Canonical shadow binding establishes field equivalence under that trust assumption.

For outbox dispatch, `ProductionDispatchReceipt.target_receipt` and `target_reason` retain the actual destination reply, while `local_event_id` identifies the durable local settlement. If an observer settled first, that event can contain only the canonical terminal classification rather than the returned transport payload. The [public terminal receipt contract](PRODUCTION_CLOSURE.md#public-terminal-receipt-contract) defines the `observed-event:` origin namespace, exact replay rules and legacy fail-closed behavior. Receipt contents and terminal settlement supply no new execution authority.

`knowledge_fact_ledger` is physically the immutable `kg_revision_fact_sets` / `kg_revision_entities` / `kg_revision_relations` subledger keyed by the owning `(memory_id, memory_revision)`. A correction creates a successor Memory revision and its complete successor fact set; a forget creates the tombstoned Memory revision and an empty fact set. There is no independent fact revision head, CAS domain, or writer. `knowledge.graph` consumes this authoritative subledger and publishes `knowledge_graph_projection`, which is rebuildable and never becomes the fact source of truth.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Before forward migration, [cognitive_store_schema_admission.rs](../../../codex-rs/hepta-memory/src/cognitive_store_schema_admission.rs)
admits only a bounded, continuous prefix of the compiled migration history.
It checks migration-row types, sizes, versions, descriptions, success and checksums,
then compares every SQLite schema object with the corresponding compiled in-memory
reference. After schema admission and before `MIGRATOR` executes, an existing
`cognitive_meta` row receives bounded type and owner validation against
`layout.agent_id()`. Missing metadata can initialize only when every logical
application table is empty; FTS internal default rows are not application state.
Existing local owner columns and operation subjects must match the layout before
migration. The admitted prefix also receives the shared logical row/byte budget
check. Orphan state and foreign ownership are rejected without advancing history.
Clean historical prefixes can upgrade; altered CHECK expressions,
triggers, autoindexes or FTS shadow definitions are rejected before pending
migrations execute. When initialization or upgrade is needed, one `BEGIN IMMEDIATE`
transaction serializes prefix admission, existing-owner validation, compiled
migrations, full-schema verification and owner metadata initialization.
Every reopen verifier authenticates schema and budgets in the same SQLite
transaction as its reads or integrity command. Journal materialization repeats
its admission in the exact read snapshot; a pool connection cannot substitute
unverified executable schema after the admission cut. The logical recovery anchor binds registered
owner tables; FTS shadow definitions are authenticated, while their physical
contents remain rebuildable index state.

Owner admission first reads the fixed SQLite header scalar `PRAGMA encoding` and requires `UTF-8`, inside the existing `BEGIN IMMEDIATE` transaction. This header read does not evaluate owner-defined SQL and precedes SQLx/schema text byte-bounds, exact historical schema admission, budget and owner checks, and migrations. UTF-16 databases are refused even when their historical application tables are empty: their `CAST(TEXT AS BLOB)` bytes cannot supply the UTF-8 canonical Memory contract or its metadata byte limits. The historical encoding-denial fixture retains the predecessor image and cold file bytes; it does not perform an implicit encoding conversion.

For an already-owned current store, the private `MigrationAdmission::AlreadyCurrentOwned` result requires the complete successful compiled migration prefix through 0019, exact schema, global budget, all local-owner checks and exactly one valid matching metadata singleton. `open` explicitly rolls back that initial fence, skips `MIGRATOR`, metadata insertion and the redundant initialization commit, then runs the unchanged `verify_store` path. Every verifier independently admits its fresh transaction cut; no validation proof is carried across the rollback. Canonical stable-ledger SHA verification therefore runs once on this path. This result supplies no production authority or independent current-cut witness. [Current refusal fixtures](../../../codex-rs/hepta-memory/src/cognitive_store_schema_ownership_tests.rs) preserve the complete image and cold bytes for a corrupt current Source and for empty metadata with corrupt physical FTS state despite zero logical FTS rows.

When initialization or upgrade is needed for a nonempty compiled prefix, schema, budget and all existing-owner checks precede bounded Source/Memory canonical content-digest, current-head, citation and Memory FTS verification in that same transaction, before `MIGRATOR`. Historical prefixes and current stores with empty metadata retain this path. The tables are stable from migration 0001: every retained Memory identity must have its latest revision as its current head, each revision has 1–32 citations with contiguous zero-based ordinals and the exact same owner/scope as its sources, and FTS must have exact ledger membership/content plus inverted-index integrity. Valid historical prefixes still upgrade; known corrupt history rejects before migration 0003 can delete old KG projection evidence. The [real-v2 historical corruption matrix](../../../codex-rs/hepta-memory/src/cognitive_store_schema_ownership_tests.rs) compares complete schema, SQLx history, owner, Source/Memory/citations, generation-7 KG and cold source on denial, including missing heads and heads rolled back behind retained history. This historical admission does not claim complete semantic validation of arbitrary old KG state, and its source is not a passing execution receipt.

Stable verification explicitly checks typed metadata before bounded 64-row materialization, then parses scope, source kind, verification, lifecycle, digest and ID grammar; historical `memory:v1:` IDs remain supported. Workspace digests require the complete 64 lowercase hexadecimal bytes, and tombstone reasons must be nonblank under Unicode `trim()` and at most 256 UTF-8 bytes. Memory content must be valid UTF-8; Source content retains its arbitrary-byte contract. NULL-safe history checks require an absent predecessor for revision 1, the immediately preceding retained revision for every successor, unchanged scope and no transition from tombstoned to active. Memory FTS requires TEXT ID/content and INTEGER revision columns before exact membership checks, preventing storage-type aliases from hiding a missing revision. These checks supplement SQLite CHECK expressions that can accept NULL, without introducing new authority or stricter historical ID formats. A companion positive fixture covers upgrade and reopen of a valid two-revision `memory:v1:` ledger.

The public `StableMemoryId::parse` contract also accepts both exact `memory:v1:` and `memory:v2:` prefixes, each followed by precisely 64 lowercase hexadecimal bytes; malformed digests and other versions reject. New identities still use the v2 hashing domain. Migrated v1 IDs remain verbatim through latest-head reads, ranked retrieval, source explanation, correction and reopen. The [public legacy compatibility regression](../../../codex-rs/hepta-memory/src/cognitive_model_legacy_tests.rs) covers those operations, current-head filtering of historical FTS matches, creation of a fresh v2 identity and negative grammar cases. Compatibility adds neither write authority nor an identity rewrite.

After exact schema, full-budget and all owner checks, the needs-initialization path runs `SELECT 1 FROM pragma_foreign_key_check LIMIT 1` in that same transaction before stable-ledger verification. Any violation rejects without materializing violation payloads. After stable-ledger checks, `PRAGMA quick_check(1)` must return exactly the single value `ok` before `MIGRATOR` runs. Dangling-source-citation, orphan-Memory-head, invalid CHECK validity-range and same-owner cross-workspace citation cases preserve the entire historical image and cold file bytes. These checks add neither authority nor a claim of complete old KG semantic validation.

[Migration 0016](../../../codex-rs/hepta-memory/migrations/0016_memory_citations_source_lookup.sql) adds the covering `memory_citations(source_id, source_revision)` index for reverse citation/source-frontier lookups.

[Migration 0017](../../../codex-rs/hepta-memory/migrations/0017_kg_storage_count_admission.sql) replaces the generation-storage count trigger. Node and edge counts independently inspect their actual immutable fact table: `CASE` yields zero only when that table is genuinely empty, without trusting a declared receipt count. Otherwise the trigger deduplicates scoped Memory identities at or before the requested generation, selects each latest historical trigger with indexed `MAX(generation)`, and counts its revision facts with the original `verification = 'verified'` and `lifecycle = 'active'` filters. Matching receipt/semantics scope and generation remain required; current heads do not replace the historical cut.

[Migration 0018](../../../codex-rs/hepta-memory/migrations/0018_memory_revisions_scope_frontier.sql) adds the covering `memory_revisions(owner_agent_id, scope_kind, workspace_sha256, lifecycle, memory_id, revision)` index for retained revision frontiers. The existing aggregate SQL, owner/scope predicates, lifecycle/history counts and uniquely keyed fact-set lookup remain unchanged.

[Migration 0019](../../../codex-rs/hepta-memory/migrations/0019_source_ledger_scope_frontier.sql) adds the ordinary, non-unique covering `source_ledger(owner_agent_id, scope_kind, workspace_sha256, source_id, source_revision)` index for the KG cited-Source frontier, avoiding payload reads for the covered scope and identity fields. Its `COUNT` SQL is unchanged: owner/scope/workspace must match and an exact `(source_id, source_revision)` citation must exist. Uncited Source appends remain outside this graph frontier, while the broader Lane-C owner cut still fences all Source changes. The compiled oracle for 131 required schema objects is `daba235025b667251c5d6b5500db5ab8b0096f32c5bc0222ef78ec2b88026f5c`, distinct from the complete 188-row catalog reference. These migrations change authenticated schema identity, not semantic digest algorithms or binding scope; native qualification for the new source remains pending.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/cognitive.store.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.store.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/cognitive.store.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.store.md). Descriptor-bound writable recovery is source-implemented, but an independently authenticated current-cut witness and externally verified production authority remain mandatory host inputs; source fixtures cannot manufacture either fact or replace an external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.store.md) specifies the algorithm and pilot ceilings. Current native bounds are enforced in [hepta-cognitive-store](../../../codex-rs/hepta-cognitive-store/src/lib.rs) and [Lane C SQLite](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md). The durable measurement executable [cognitive_store_perf.rs](../../../codex-rs/hepta-memory/examples/cognitive_store_perf.rs) records cold-open, per-commit p50/p95/p99/max, database/WAL/journal bytes, snapshot materialization, recovery-anchor cost and reopen cost. The focused owner qualification workflow configures a 256-record latency sample and a 16,384-record maximum-retained profile. The reusable consolidated qualification also configures these measurements for durable-owner changes. Dependency-selected ordinary native checks do not imply that either profile executed. Measurements are exact-run artifacts, not prose claims or deployment thresholds.

Canonical KG snapshot reads traverse actual Memory heads in `h.memory_id` order. The projection builder uses `memory_heads h CROSS JOIN memory_revisions r` with the same ID/revision `ON` condition to keep the heads table first; migration 0018 must not turn a 512-head workload into a scan of its 16,384 retained revisions. Returned fields, owner/scope filtering, the declared/actual entity and relation counts, order and bounded `LIMIT` remain unchanged. A synthetic SQL-only model reduced head-query SQLite VM instructions by about 83%; it is not native qualification, and distributions with many other-scope heads are not guaranteed faster. Historical node and edge reconstruction first deduplicates `(projection_scope, trigger_memory_id)` identities at the requested generation, then uses an indexed `MAX(generation)` lookup for each identity. This selects the exact historical cut rather than substituting current heads, and retains scope checks, deterministic output order, capacity caps and bounded query limits. Memory, tombstone and fact frontiers share one aggregate over revisions and their uniquely keyed fact receipts; the exact counts and source-vector digest inputs are unchanged. Isolated SQL measurements below explain optimization choices; neither they nor results from an earlier source qualify native latency or the maximum-retained profile for the new source.

The builder hashes checked borrowed head-row fields instead of constructing a temporary `Vec<ProjectionHead>` with copied strings. Missing fact receipts reject, declared entity/relation counts must equal both actual counts, and the fact-set digest retains its strict lowercase-SHA validation. This still allocates for that digest validation. Both row and reference paths share the original domain, scope, big-endian head count and six-field framing, including the big-endian revision; receipt digests are unchanged. The builder drops all head rows before its next await. Reopen still decodes the independent `ProjectionHead` representation and recomputes the reference digest. [Head-digest regressions](../../../codex-rs/hepta-memory/src/cognitive_kg_head_digest_tests.rs) cover 0/1/512 rows, scopes and v1/v2 IDs, malformed actual values, missing/incomplete receipts, and public correction/reopen parity; their source is not a native pass receipt.

Logical budget framing remains 16 bytes for `NULL`, 64 for either integer or real, and `24 + octet_length(column)` for Text/Blob values. The latter replaces `24 + length(CAST(column AS BLOB))`, retaining encoded byte accounting while allowing SQLite to obtain stored column lengths without reading large overflow payloads. A separate pinned SQLite 3.51 model compared the old and new expressions for 24 typed values in each of UTF-8, UTF-16LE and UTF-16BE; accounting matched within each encoding. Encoded text lengths may differ between encodings, and owner admission still requires UTF-8; the alternate-encoding model probes do not establish supported store formats. All compiled-schema and logical-budget scans still execute on every growing commit; there is no usage cache or weakened admission boundary.

The immutable compiled query plan removes repeated budget table/column discovery and aggregation SQL rendering from growing commits, while preserving complete schema authentication and scans of actual retained owner rows. It supplies no cached capacity decision. [Budget-plan expression regressions](../../../codex-rs/hepta-memory/src/cognitive_store_budget_plan_tests.rs) compare all actual SQLite storage classes against the generic framing under every declared-type and NOT NULL hint, including Unicode, embedded NUL, invalid UTF-8 TEXT and byte-ceiling-sized values. These test sources identify equivalence scope, not a passing execution receipt.

Warm SQL-only models using the pinned SQLite C engine compiled at optimization level 2 produced these wall-time medians:

| Isolated query | Synthetic input | Before (ms) | After (ms) |
| --- | --- | ---: | ---: |
| Source logical-byte aggregate: cast length to `octet_length` | 126 Source rows, 1 MiB content each | 24.939 | 0.199 |
| Retained Memory/tombstone/fact frontier: add the 0018 covering index | 16,384 revisions across 512 heads | 24.984 | 10.241 |
| Historical 0018 catalog equality: vector fetch to scalar set comparison | All 187 compiled 0018 catalog rows | 1.158 | 0.576 |

The historical 0018 catalog scalar model used 77,402 bytes of SQL and returned one row instead of 187. Statement preparation increased from 0.021 to 0.880 ms; those preparation measurements are separate from the warm execution medians above. This illustrates a preparation cost rather than assuming the scalar path is always cheaper. These models compare equivalent query outputs on scratch SQL fixtures through a Python C-API harness. They exclude Rust/SQLx workers, pool rotation, complete schema/integrity admission, per-write synchronization, concurrent product execution and the configured performance deadline. They are not native qualification, release performance or deployment acceptance results.

A separate cited-Source-frontier SQL model used an older SQLx 0017 fixture with an equivalent experimental `18_model` covering index. The existing owner/scope predicates and citation `EXISTS` returned the same count of 16,384 before and after. SQLite VM instructions decreased from 213,008 to 131,090, wall time from 28.002 to 9.616 ms and CPU time from 20.747 to 7.552 ms. This is an isolated model of the index choice, not native execution of the compiled 0019 migration or a store-admission/deadline pass. Flattening budget queries into a `UNION ALL` aggregate was not adopted: its separate model showed a slight regression, and the per-table actual-state scans remain unchanged.

The ordinary dev/test package overrides in [Cargo.toml](../../../codex-rs/Cargo.toml) now set only `libsqlite3-sys` to optimization level 3, which its build script also applies to the bundled SQLite C engine for all consumers of those profiles. Rust owner code remains at its ordinary optimization level 0, release remains at level 3, and debug/overflow checks, capacity limits, benchmark payloads and deadlines are unchanged. This build configuration is not a production release performance claim.

A separate O2/O3 C-API model used identical SQLite 3.51.3 source identity and compile-option macros on the read-only older SQLx 0017 plus `18_model` fixture. Its 32 logical-budget table queries produced identical 131,790 rows, 115,892,874 logical bytes, maximum row size 5,107 bytes and 8,722,041 VM instructions. CPU time decreased from 333.512 to 278.907 ms, about 16.4%; wall time decreased from 1,500.249 to 1,285.472 ms under substantial host contention. These observations do not establish the native effect of OPT3 or passing full-owner/max-profile latency. Another isolated catalog model reduced the two-direction scalar to the three-condition single-direction proof from 0.7953 to 0.3763 ms and 6,248 to 3,784 VM instructions. That measures SQL execution only; complete migration/count/byte admission, typed fallback and exact-candidate native results remain required.

An exploratory local maximum-retained run using the optimization-level-2 SQLite build and migration 0018 exceeded the unchanged 1,200-second deadline. For the later clean `126c6f87ae2a05e825c86cec9c62ab6cc0e69ed5`, the default-profile local maximum run failed at 1,200.072578 seconds with last recorded progress at 13,824 of 16,384 revisions; the corresponding GitHub source-head run failed at 1,200.064049 seconds with last progress at 13,312. These are separate actual runs, not transferred timing/progress. Neither failure qualifies that run or later source. The new 0019/OPT3 candidate's native qualification remains pending; no earlier result is transferred to it, and default-profile exact-candidate CI results remain required.

Commit admission scans retained logical state and the complete actual catalog on every growing commit. Schema equality can run as a SQLite set scan instead of a Rust full fetch; actual-state `COUNT`/`SUM`/`MAX` scans still run in the same transaction. The logical limits bound admitted state, not scan latency or physical database size; the citation index does not remove this full-scan cost. Per-chain ingress also preserves reopen ceilings: compact and lease histories each retain at most 4,096 rows, and the logical-turn registry admits at most 16,384. Compact checks both post-mutation length and the shared `insert_event` sequence used by direct atomic witness writes, retaining exact replay. A takeover from registry row 16,383 can fit its superseded row 16,384, but its winner row 16,385 rejects and rolls back all registry and lease changes. H7 retains a defensive 16,384-row append guard after replay; its current legal start/terminal state machine reaches at most two rows.

A global terminal-capacity reserve is not implemented. At the aggregate limit, ACK, reconciliation, revocation or lease-finalization writes can reject; the unchanged durable state remains reopenable, but terminal progress is not guaranteed. Shared-experience policy revision 1,025 reserves only a local revocation slot after 1,024 ordinary revisions. It cannot override the global owner budget or establish guaranteed withdrawal at global capacity. Authoritative append-only history remains retained; these optimizations implement no long-term retention or garbage-collection policy.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

The physical writer remains `hepta-memory::CognitiveStore` over `cognitive_1.sqlite3`; `hepta-cognitive-store::durable` is the canonical façade and does not duplicate state. Lane C exposes both bounded whole-scope snapshots and proof-bound durable pages that keyset-page current heads while reconstructing complete ancestry for each selected head. Writable `open_with_recovery` is descriptor-bound and fail-closed: it copies retained database/WAL/journal bytes into a private generation, verifies the independent exact current cut and production authority/fence, checkpoints the copy, and atomically publishes the active generation.

### Canonical MemoryEvent shadow migration

`append_admitted_with_canonical_shadow` validates canonical `MemoryEventV1`, the legacy admission candidate, verification-state correspondence, and the exact source ID/digest/observed-time set before invoking the existing admitted append. The deny-all sidecar binds canonical event digest, legacy candidate digest, final record digest, snapshot-vector digest and write disposition. This folds the useful #970 source work into the canonical #694 line without creating another writer. The production path additionally emits `ProductionCognitiveMutationReceiptV1`, which is committed in the same SQLite transaction as the source/Memory/fact/projection mutation and carries the authoritative `SourceRevisionId`, source-content SHA-256 and observation time. `bind_canonical_event_to_durable_receipt` checks source-ID/digest/revision/time equivalence against an authenticated owner receipt; it supplies no independent producer-authentication or freshness proof. The legacy shadow alone still makes no source-revision claim.

Current operating and state-format references:

- [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-cognitive-store/src/v2_tests.rs](../../../codex-rs/hepta-cognitive-store/src/v2_tests.rs): verified-only admission, reserved tombstone capacity, bounded retry journal, cross-object image validation and exact-cut page cursors.
- [codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs): durable owner writes, correction/deletion ancestry, proof-bound paging, reopen and rollback-cut checks.
- [codex-rs/hepta-memory/src/cognitive_store_recovery_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_store_recovery_tests.rs): descriptor-bound writable recovery, exclusive fencing, current-cut rejection and hostile filesystem identities.
- [compiled-schema admission tests](../../../codex-rs/hepta-memory/src/cognitive_store_schema_admission_tests.rs) and [hostile-schema recovery tests](../../../codex-rs/hepta-memory/src/cognitive_store_schema_tests.rs): forward upgrade from compiled historical prefixes; schema rejection before migration or integrity scans.
- [cognitive_store_schema_catalog_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_store_schema_catalog_tests.rs): scalar/vector parity over the complete catalog, NULL-SQL autoindexes and FTS shadows, data-only catalog mutations, duplicate-count necessity and unchanged byte bounds.
- [codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs](../../../codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs): named Agentd product host through the canonical cognitive-store façade.
- [codex-rs/hepta-memory/src/production_writer.rs](../../../codex-rs/hepta-memory/src/production_writer.rs): same-transaction production provenance, semantic-validation rollback, live-authority rejection, and response-loss/restart duplicate rejection (`semantic_response_loss_restart_rejects_duplicate_and_preserves_committed_cut`).
- [cognitive_store_budget_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_store_budget_tests.rs): public maximum-size Source appends reach the shared budget; sealed production remember rejects twice without changing owner counts, recovery anchor or reopen state.
- [cognitive_store_budget_plan_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_store_budget_plan_tests.rs): immutable plan byte-framing equivalence across actual storage classes, declared-type/NOT NULL violations and Unicode/NUL/invalid-UTF-8/byte-ceiling values.
- [cognitive_model_legacy_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_model_legacy_tests.rs): public v1/v2 grammar, actual historical migration, latest/retrieval/correction/explanation/reopen without rewriting legacy IDs, and new v2 creation.
- [cognitive_kg_head_digest_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_kg_head_digest_tests.rs): checked borrowed-row/reference digest parity, negative receipt/type/UTF-8 cases and public correction/reopen with independent digest reconstruction.
- [production_operation_claim_clock_tests.rs](../../../codex-rs/hepta-memory/src/production_operation_claim_clock_tests.rs): real SQLite lock waits and writer/claim expiry; final-use persistence and retained-verifier ordering at actual target entry.
- [local_compact_executor_capacity_tests.rs](../../../codex-rs/hepta-memory/src/local_compact_executor_capacity_tests.rs), [local_lease_outbox_capacity_tests.rs](../../../codex-rs/hepta-memory/src/local_lease_outbox_capacity_tests.rs) and [logical_turn_registry_capacity_tests.rs](../../../codex-rs/hepta-memory/src/logical_turn_registry_capacity_tests.rs): valid near-limit hash chains, public ingress rejection, exact replay and reopen; the registry case verifies whole-transaction rollback when takeover's second append exceeds its cap.
- [codex-rs/hepta-cognitive-store/src/lib_tests.rs](../../../codex-rs/hepta-cognitive-store/src/lib_tests.rs); named case: `append_and_correction_are_predecessor_fenced`.

The ordinary [nextest configuration](../../../codex-rs/.config/nextest.toml) assigns the real Source-budget fixture and `codex-hepta-memory` `capacity_tests::` fixtures to the existing `hepta_durable_capacity` group with `max-threads = 1`, reducing concurrent disk contention. A narrower exact-name override assigns `threads-required = 'num-test-threads'` only to `codex-hepta-memory`'s `cognitive_store::budget::tests::legal_source_appends_stop_atomically_at_reopen_budget_and_replay_at_capacity`, reserving this nextest invocation's slots while the full 128 MiB fixture runs. It does not isolate unrelated processes, change other tests' quotas or establish a latency pass. The default 60-second watchdog and one retry remain in force, as do the full capacity limits and fixture payloads. The separate maximum-retained performance profile retains its 1,200-second deadline.

Ordinary development follows [the global development policy](../../DEVELOPMENT.md#1-mission-and-truthful-completion-model): edit the owned source, run affected package tests and applicable review checks, then use the normal protected branch. From the repository root, `python3 scripts/hepta-docs.py verify --profile development` validates current working-tree ownership, schemas, registered paths and references, including uncommitted edits. Historical qualification inventories and handwritten execution receipts are not additional permission to implement or merge an authorized source change.

In `codex-rs`, run `just test -p codex-hepta-memory -p codex-hepta-cognitive-store`. The command is a test invocation, not a stored result. Inspect its output for passes, failures and skips. Explicit qualification uses `--profile qualification` with committed candidate inputs and retains exact source-head and merge-candidate evidence when the selected qualification requires them. A development-profile pass supplies no execution, activation or acceptance fact. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/cognitive.store.md) separately labels target acceptance designs.

From the repository root, the selected integration/recovery checks are:

```sh
just test --locked --lib -p codex-hepta-agentd --no-tests fail -E 'test(cognitive_) | test(production_writer_host)'
just test --locked -p codex-hepta-agentd --test cognitive_store_product_writer --no-tests fail
just test --locked --lib -p codex-state --no-tests fail -E 'test(sqlite_recovery)'
```

The [architecture convergence workflow](../../../.github/workflows/hepta-architecture-convergence.yml) configures these selections for its source-head/base-merge lanes under the existing native-execution and effects/learning/lifecycle conditions. It records command execution or exact-tree reuse separately. These are Agentd cognitive/context and production-writer-host library checks, the default-profile named Agentd product-host recovery/writer integration, and state SQLite recovery checks. The qualification-only write seam and independently selected deployment-host acceptance remain separate. Workflow configuration alone supplies no execution claim; retain the current exact-run results before treating this scope as verified.

At `126c6f87ae2a05e825c86cec9c62ab6cc0e69ed5`, the source-head architecture lane passed 32 selected Agentd library tests, then failed its one product-writer integration test on the old fixture's pre/post writer-acquisition anchor equality assertion. The subsequent state SQLite recovery command did not execute because that same step stopped on failure. The fixture now rejects an exact bad state digest without changing the original cut, distinguishes recovery from the legitimate ACTIVE writer-lease append, and requires the complete post-semantic/release anchor to equal ordinary reopen. This changes the test's comparison boundary, not production authority, live clocks, TTL or recovery gates. The corrected integration on the new candidate still needs real execution; no product or state PASS is inferred.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `MEM-1-STORE`
- `MEM-8-PRODUCTION-WRITER`

The bootstrap package is `MEM-1-STORE`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source completion for the declared scope requires code in the registered root, public surfaces matching the registries and passing affected tests. Qualification separately requires current exact-candidate evidence for its selected boundary, including source-head and merge-candidate checks where declared. Ordinary source development does not require runtime qualification records merely to merge. Later planned packages may remain without invalidating documentation closure; production-writer authority, authenticated current-cut recovery and activation gates remain mandatory whenever those runtime boundaries are exercised.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

### Adversarial development checks

Recovery images must reconstruct a legal per-record commit order, preserve the
ordinary/tombstone and retry-journal capacity budgets, and bind each unchanged
receipt to the head actually visible at its recorded cut. Full snapshot receipts
must agree on generation, sequence and complete lineage. A tombstone cannot be
a genesis record or have a successor. Image checksums establish internal
consistency, not independent authenticity or freshness.

Ordinary SQLite open rejects redirected, multiply linked, nonregular or unsafe
permission database/sidecar identities before SQLite access. Before CHECK constraints
are used to establish ledger validity, the owner verifies its compiled schema
and migration-ledger schema. Production recovery revalidates source descriptor identity during
materialization while retaining the exclusive store fence; it rechecks that fence,
external authority and lease expiry immediately before pointer publication. Production
semantic mutations recheck the retained verifier after taking the SQLite write
lock and before commit; denial rolls back their semantic and provenance writes.

Live dispatch clocks resolve only after `BEGIN IMMEDIATE`, operation-fence and claim-head reads. Claim, renewal and `Entered` enforce the persisted writer deadline at this serialized cut; short operation TTL and retry-eligibility decisions use the same time, and renewal or `Entered` cannot revive an expired claim. Explicit `*_at` APIs keep their supplied deterministic time and do not prove real-world current authorization. No tolerance or clock clamp bypasses expiry. After final-use nonce persistence, dispatch runs the retained-verifier precheck, final live-grant verification, cheap writer-deadline and short-claim-TTL checks, then actual target entry without an intervening await. Failed entry consumes the nonce; it creates no retry authority. Settling already-entered work still requires the active owner generation/token, without adding a wall-expiry prohibition on convergence. Exact-candidate regression results remain required.

The [production route and remaining gates](PRODUCTION_CLOSURE.md) identify the
compiled façade, host composition, cutover and rollback procedure. Agentd now consumes bounded exact-ID owner snapshots, sharing a global head/visibility witness across candidate, output and final-use selections. Each selected ancestry remains bounded; global witness scanning has bounded RAM and scope-dependent latency. Publication and final-use revalidate the complete owner witness after their last provider, ranker or learning await. Prepublication learning records retain assignments without claiming consumer exposure or a returned snapshot; positive delivery needs independently observed consumer acknowledgement.

ExactCurrentCut recovery authenticates and preserves the complete supplied cut at its own boundary. Later writer acquisition may append a new host-bound ACTIVE lease to `cognitive_local_leases`, which the complete recovery anchor includes; its state digest then legitimately changes while owner, profile and schema stay equal. Comparing those identity fields after acquisition does not replace exact pre-acquisition witness validation. A wrong full state digest must still refuse without changing the source cut, and the final post-semantic/release complete anchor must match ordinary reopen. Independently retained current-cut evidence must track subsequent durable writes.

The focused native gate is [hepta-cognitive-store-native.yml](../../../.github/workflows/hepta-cognitive-store-native.yml).
It qualifies both the exact source head and deterministic base-merge candidate
with the two owner-library test suites. Its strict Clippy command selects only
`codex-hepta-cognitive-store` and `codex-hepta-memory`, uses `--no-deps` and retains
`-D warnings`; dependency compilation remains required. The source-head job also
invokes crash/reopen recovery, a 256-distinct-head latency sample, and a
16,384-retained-revision profile using 512 heads with 32 revisions each. The
maximum workload performs real corrections and keeps the independent KG head
limit unchanged; its artifacts distinguish retained revisions from active heads. These configured commands do not establish successful
execution receipts. This gate runs independently of whole-repository
document validation. It supplies scoped native evidence and does not replace
global source/caller/document gates, Agentd integration qualification or independent
production acceptance.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `cognitive.store`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `MEM-1-STORE`

- State: `source_implemented_execution_pending`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `cognitive-platform` / `durability-kernel`.
- Allowed write paths:
- `codex-rs/hepta-cognitive-store/**`
- Development predecessors:
- `MEM-0-TYPES`
- Activation predecessors:
- `MEM-0-TYPES`
- Required deliverables:
- `exact_source_identity`
- `source_inventory`
- `static_verification`
- `focused_tests`
- `package_tests`
- `all_target_check`
- `strict_lint`
- `clean_worktree`
- `exact_head_execution`
- `merge_candidate_execution`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `MEM-8-PRODUCTION-WRITER`

- State: `source_implemented_execution_pending`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `cognitive-platform` / `durability-kernel`.
- Allowed write paths:
- `codex-rs/hepta-cognitive-store/**`
- `codex-rs/hepta-memory/src/cognitive_store.rs`
- `codex-rs/hepta-memory/src/cognitive_store_recovery.rs`
- `codex-rs/hepta-memory/src/cognitive_store_recovery_tests.rs`
- `codex-rs/hepta-memory/src/cognitive_store_tests.rs`
- `codex-rs/hepta-memory/src/lib.rs`
- Development predecessors:
- `MEM-1-STORE`
- Activation predecessors:
- `MEM-1-STORE`
- `P0.7B-B4-CALLSITE-PROOF`
- Required deliverables:
- `exact_source_identity`
- `source_inventory`
- `static_verification`
- `focused_tests`
- `package_tests`
- `all_target_check`
- `strict_lint`
- `clean_worktree`
- `exact_head_execution`
- `merge_candidate_execution`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `cognitive.store` to primary lane `LANE-C-MEMORY`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

### Readiness implementation work packages

The following additional work packages are source-planning envelopes introduced by the readiness overlay; they do not imply implementation or activation:

- `EMB-1-SENSOR-BUS-BODY-SCHEMA`

## 17. Source implementation receipt

The bootstrap source-location obligation for `cognitive.store` is implemented by work package `MEM-1-STORE` in:

- `codex-rs/hepta-cognitive-store`

Ordinary document validation uses the development profile against the current working tree. Native development CI selects affected owners and reverse consumers from both the base and candidate Cargo dependency graphs. The reusable `.github/workflows/hepta-consolidated-source.yml` supplies dependency-selected native checks or explicitly requested full qualification; its executed scope and command outputs must be inspected rather than inferred from the workflow name. The focused cognitive owner qualification is described in section 14. Qualification profiles retain committed source identities and their declared inventory and evidence checks. A workflow definition or source-navigation binding is not a successful execution receipt. Actual source implementation receipts grant no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion or release authority.

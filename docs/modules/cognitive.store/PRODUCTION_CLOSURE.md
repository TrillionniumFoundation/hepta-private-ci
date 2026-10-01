# cognitive.store production convergence

Status: source implementation and product composition exist; current
candidate qualification and declared module completion gates remain pending.
External bootstrap, independent acceptance, activation and production execution
are separate states.

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

If authority fails before commit, the entire semantic transaction rolls back.
The external verifier must provide current revocation semantics; source code
cannot manufacture those semantics or atomically freeze an external authority.

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
autoindexes and FTS shadow definitions. Prefix admission, existing-owner validation,
compiled migrations, full-schema verification and owner metadata initialization share one
`BEGIN IMMEDIATE` transaction. The completed schema is verified again
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

The focused native owner workflow runs strict Clippy for
`codex-hepta-cognitive-store` and `codex-hepta-memory` with `--no-deps` and
`-D warnings`. It compiles dependencies while limiting lint qualification to
these two owner crates. Whole-repository and Agentd qualification remain
separate gates. Crash/reopen and both configured performance profiles require
their own successful exact-run receipts; workflow definitions are not results.

The registry keeps `production_implementation=false` while current candidate
qualification and declared module completion gates are pending. This fact does
not erase the compiled source or named product composition. The repository does
not provision the external issuer, authenticated current-cut witness service or
operator acceptance; those remain independent host lifecycle obligations.

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
opposite results, stale fences and different actual receipt replays remain errors. A missing source row remains unresolved until a trusted
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

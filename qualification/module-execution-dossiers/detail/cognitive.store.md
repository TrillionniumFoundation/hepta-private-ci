# cognitive.store: implementation design

Parent: `docs/modules/cognitive.store/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Canonical repository-controlled current status: [`docs/modules/cognitive.store/STATUS.json`](../../../docs/modules/cognitive.store/STATUS.json). Source implementation and production implementation now exist; exact-candidate execution, writable suspect-image recovery, independent acceptance, activation and release remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`.

## 1. Source and work envelope

Root: `codex-rs/hepta-cognitive-store`. Packages: `MEM-1-STORE`, `MEM-8-PRODUCTION-WRITER`.

**Implemented entrypoints:** `open_authoritative` in [../../../codex-rs/hepta-cognitive-store/src/lib.rs](../../../codex-rs/hepta-cognitive-store/src/lib.rs); `CognitiveStore` in [../../../codex-rs/hepta-memory/src/cognitive_store.rs](../../../codex-rs/hepta-memory/src/cognitive_store.rs); `lane_c_snapshot` in [../../../codex-rs/hepta-memory/src/lane_c_snapshot.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot.rs).

The module owns the product ingress while delegating SQLite persistence mechanics to the existing `hepta-memory::CognitiveStore`. That delegation must never become a second product-open API. Qualification semantic stores in `hepta-cognitive-store` are not production writers.

## 2. Public operations and contract details

Canonical production open: `codex_hepta_cognitive_store::open_authoritative(layout) -> CognitiveStore`.

Cold exact-cut read recovery: `open_authoritative_read_only_recovery(layout, requirement) -> RecoveredCognitiveReadOnly`.

Durable memory operations remain the owner methods implemented by the delegated SQLite engine: append/create, exact-head correction, forget/tombstone, source/citation write, coherent Lane-C snapshot and production-writer lease/outbox operations. Product/runtime code obtains that owner through the `cognitive.store` façade.

## 3. State records and transaction design

Memory authority is immutable `memory_revisions` plus current `memory_heads`, source/citation lineage and tombstones. Knowledge facts use a **memory-revision-bound durable projection** in `kg_revision_fact_sets`; they do not form a separately writable second ledger. `CognitiveOwnerFrontiers.knowledge_facts` exposes the fact-set frontier in the coherent owner cut.

One logical memory mutation uses one bounded SQLite transaction. Correction performs exact expected-head CAS. Tombstone resurrection is rejected. Publication/occurrence state for production effects is durable and fenced by the production writer protocol.

`QualificationSemanticStore` and `AdmittedCognitiveStoreV2` model semantics in memory only. They are never backfill destinations, shadow stores or runtime fallbacks.

## 4. Deterministic algorithm and scheduling

Authenticate owner/scope; validate source/citations and bounds; verify predecessor/current head; append immutable revision; publish its revision-bound fact projection; advance the head/projection in the same owner transaction; commit under the required SQLite durability profile; only then return local success.

Production external-effect dispatch additionally requires an externally verified authority lease, writer/owner epochs, generation/fencing token, lifetime OS writer lock and one durable dispatch claim before target invocation. Unknown outcomes remain `Indeterminate`.

## 5. Capacity and performance profile

All existing native bounds remain authoritative. Measure fsync/WAL growth, maximum bounded snapshot materialization, recovery-anchor capture, reopen, tombstone traversal and production-writer contention at the selected target host. Source tests do not constitute hardware power-loss qualification.

## 6. Concrete verification cases

- STORE-01: identical semantic retry returns the prior commit; drift conflicts.
- STORE-02: real SQLite façade open/drop/reopen preserves the exact recovery anchor.
- STORE-03: second production writer is rejected while the first lifetime lock is held.
- STORE-04: crash after target send reopens as durable `Indeterminate` and cannot redispatch the stale receipt.
- STORE-05: concurrent dispatchers create one durable claim and at most one target call.
- STORE-06: correction/tombstone survive SQLite reopen and preserve ancestry/frontiers.
- STORE-07: product Agentd openers contain no direct `CognitiveStore::open` bypass.
- STORE-08: failed/revoked recovery never falls back to ordinary open.

The named source tests are evidence identities; exact-candidate CI supplies pass/fail receipts.

## 7. Integration, migration and rollback

Agentd runtime and production writer host now enter the durable owner through `codex_hepta_cognitive_store::open_authoritative`. The physical database does not move, so this authority convergence is an ingress cutover rather than a data-copy migration. The complete cutover/rollback runbook is [`docs/modules/cognitive.store/MIGRATION.md`](../../../docs/modules/cognitive.store/MIGRATION.md).

Do not create another cognitive database. Do not dual-write V2 and SQLite. Before any binary rollback involving a suspect/older image, require independently authenticated current-cut recovery admission; never restore an old valid backup through ordinary open.

## 8. Current native implementation

- **Canonical façade:** `open_authoritative`, durable `CognitiveStore` re-export and read-only recovery ingress in [codex-rs/hepta-cognitive-store/src/lib.rs](../../../codex-rs/hepta-cognitive-store/src/lib.rs).
- **Qualification-only semantic stores:** `QualificationSemanticStore` and `AdmittedCognitiveStoreV2` in the same module root.
- **Durable persistence engine:** [codex-rs/hepta-memory/src/cognitive_store.rs](../../../codex-rs/hepta-memory/src/cognitive_store.rs), file `cognitive_1.sqlite3`.
- **Durable memory/fact semantics:** memory revisions and `kg_revision_fact_sets`; coherent projection in [codex-rs/hepta-memory/src/lane_c_snapshot.rs](../../../codex-rs/hepta-memory/src/lane_c_snapshot.rs).
- **Product callers:** [codex-rs/hepta-agentd/src/runtime.rs](../../../codex-rs/hepta-agentd/src/runtime.rs) and [codex-rs/hepta-agentd/src/production_writer_host.rs](../../../codex-rs/hepta-agentd/src/production_writer_host.rs).
- **Single writer/crash/concurrency source tests:** [codex-rs/hepta-memory/src/production_writer.rs](../../../codex-rs/hepta-memory/src/production_writer.rs).
- **Real durable façade reopen test:** [codex-rs/hepta-cognitive-store/tests/durable_authority.rs](../../../codex-rs/hepta-cognitive-store/tests/durable_authority.rs).
- **Drift gate:** [scripts/hepta_cognitive_store_authority.py](../../../scripts/hepta_cognitive_store_authority.py).
- **Operating reference:** [codex-rs/hepta-memory/LANE_C_SQLITE.md](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md).

### Remaining closure boundary

Writable restoration of a suspect/rollback-capable database remains fail-closed. The missing primitive is a descriptor-bound SQLite writer VFS/non-reconnecting connection plus an independently current host writer fence. Pathname fallback is explicitly prohibited. Exact-current-cut cold recovery is available read-only; normal current-owner open is production-capable.

Exact-head CI, synthetic-merge CI, target-host execution and independent acceptance must still be recorded before qualification/activation/release claims change.

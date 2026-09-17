# cognitive.store technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Module:** `cognitive.store`  
**Owner:** `cognitive-platform`  
**Deputy:** `durability-kernel`  
**Lifecycle:** `target`  
**Source status:** `existing_bound`  
**Bootstrap work package:** `MEM-1-STORE`

Canonical repository-controlled runtime status is recorded in [`STATUS.json`](STATUS.json). The implementation map is generated/verified against that status. Exact-head CI, independent target-host qualification, operator acceptance, activation, promotion and release remain separate evidence classes.

## 1. Identity, mission and ownership

`cognitive.store` owns the authoritative Agent-local memory and knowledge-fact storage boundary: revision lineage, citations, corrections, tombstones, source/fact frontiers, integrity checks and the one product open ingress.

The module does **not** own federation networking, model calls, learning-policy writes, provider effects or another module's durable facts. Cross-owner mutation follows the registered operation/outbox protocols; a façade may sequence work but may not mint authority or become a second data owner.

The primary owner `cognitive-platform` controls the declared module root and the public ingress contract. `durability-kernel` reviews the delegated SQLite persistence engine, transaction semantics, recovery, migrations, concurrency and fault evidence.

## 2. Source binding and current implementation status

Declared exclusive module root:

- `codex-rs/hepta-cognitive-store`

The production public boundary is now:

- `codex_hepta_cognitive_store::CognitiveStore` — re-export of the existing durable Agent-local owner;
- `codex_hepta_cognitive_store::open_authoritative` — canonical normal-start product ingress;
- `codex_hepta_cognitive_store::open_authoritative_read_only_recovery` — exact-current-cut cold-image read recovery;
- `QualificationSemanticStore` and `AdmittedCognitiveStoreV2` — qualification-only semantic oracles, never production stores.

The physical persistence engine remains `hepta-memory::CognitiveStore` and `cognitive_1.sqlite3`. This is delegation of persistence mechanics, not a second product authority. Product runtime opens the owner through `cognitive.store`; the repository drift gate rejects a return to direct product opens.

Current named product callers:

- `codex-rs/hepta-agentd/src/runtime.rs` for runtime owner open;
- `codex-rs/hepta-agentd/src/production_writer_host.rs` for the externally authorized production writer.

`productionImplementation=true` means the durable implementation and named product ingress exist in source. It does **not** mean exact candidate CI, target-host execution, independent acceptance, activation or release are proven.

## 3. Boundary and single-authority topology

The canonical topology is:

```text
Agentd runtime / production writer host
                |
                v
codex_hepta_cognitive_store::open_authoritative
                |
                v
hepta-memory::CognitiveStore
                |
                v
        cognitive_1.sqlite3
```

There is no synchronized V2 database. The V1/V2 in-memory stores are deterministic semantic models used to qualify predecessor fencing, idempotency, tombstone terminality, snapshot/fence handling and image integrity. They have no production filesystem, lease or writer authority.

The repository check `scripts/hepta_cognitive_store_authority.py` protects this boundary. It verifies the façade binding, canonical Agentd openers, durable knowledge-fact representation, status document and migration runbook.

## 4. Durable memory model

The SQLite owner stores immutable memory revisions plus current heads. A logical mutation is one bounded transaction. Creation inserts revision 1 and the head. Correction appends revision `n+1`, verifies exact expected head with compare-and-swap semantics, and advances the head. Forget appends a tombstoned successor. A tombstoned memory cannot return to `active` through correction.

Source citations are bound to the committed revision. Lane-C snapshot acquisition uses one read transaction to bind revisions, citations, source state and graph/fact frontiers into one coherent cut. Consumers receive snapshot/read handles, not an independent writer connection.

The durable store verifies required schema objects and its durability profile on open. The selected SQLite profile uses WAL and `synchronous=FULL`; target-filesystem power-loss guarantees still require target-specific evidence rather than inference from PRAGMA values.

## 5. Knowledge-fact authority

The canonical knowledge-fact model is **memory-revision-bound projection**, not a second independently writable ledger.

- immutable source authority: `memory_revisions` plus citations/source lineage;
- durable fact-set representation: `kg_revision_fact_sets` bound by `(memory_id, memory_revision)`;
- read frontier: `CognitiveOwnerFrontiers.knowledge_facts`;
- graph state: rebuildable projection from the same revision/fact lineage.

Every admitted memory revision publishes its bound fact-set representation in the same owner transaction. A knowledge projection may be rebuilt, but it cannot invent an independent fact authority. The V2 `knowledge_fact_frontier` is the semantic oracle for this same rule, not evidence of a second physical ledger.

This definition resolves the former ambiguity between “fact as memory kind” and “independent fact ledger”: facts have an explicit durable projection, but their authority and revision identity remain anchored to the immutable memory revision.

## 6. Production writer and no-dual-write rule

Production writes require `ProductionDurableWriter`. The writer binds:

- externally verified `ProductionAuthorityLease`;
- Agent owner identity;
- authority and owner epochs;
- lease generation;
- fencing token digest;
- lifetime OS writer lock keyed by durable store and lease;
- durable occurrence/outbox state.

The writer lock is held for the writer lifetime, so SQLite transaction serialization cannot accidentally turn a second process into a co-owner. Lease/open logic rechecks the durable lease head after lock acquisition and rejects stale/busy writers.

Before an external target call, dispatch creates one durable claim. If the process fails after the target might have observed the request, reopen sees `Indeterminate`; it cannot silently redispatch the same receipt. Queue acceptance is never treated as provider success.

Direct product calls to `hepta-memory::CognitiveStore::open` are prohibited. Internal persistence tests and the engine itself may open fixtures directly.

## 7. Restart, concurrency and crash evidence

The repository contains two distinct test layers:

1. **semantic image tests** in `hepta-cognitive-store/src/v2_tests.rs`, which validate deterministic image/checksum/revision/journal semantics; and
2. **real durable SQLite tests** in `hepta-memory` plus `hepta-cognitive-store/tests/durable_authority.rs`.

The production writer tests include restart replay of the exact bound lease, rejection of a second writer while the first lifetime lock is held, crash-after-target-send recovery to durable `Indeterminate`, and concurrent dispatcher single-claim behavior. The façade test opens a real `cognitive_1.sqlite3`, captures a recovery anchor, drops the handle, reopens through the canonical `cognitive.store` ingress and verifies the exact durable cut is unchanged.

These source tests are materially stronger than `export_image -> reopen`, but they remain source test identities until exact-candidate CI supplies execution receipts. Multi-host filesystem/power-loss qualification remains a target-host evidence gate.

## 8. Recovery model

Recovery has three deliberately different states:

### 8.1 Normal current-owner open

`open_authoritative` delegates to the verified SQLite owner open. It creates/opens the current Agent-local database, applies approved migrations, verifies required schema/integrity constraints and returns the durable owner.

### 8.2 Exact-current-cut cold-image read recovery

`open_authoritative_read_only_recovery` requires an independently retained `CognitiveRecoveryAnchor`. On Unix it binds the existing database and sidecar identities, rejects present WAL/SHM/journal sidecars, copies the retained descriptor into a bounded read-only SQLite image, compares the complete logical cut and runs integrity checking before exposing a read-only Lane-C projection. `Revoked` denies before filesystem access. Failure never falls back to normal open.

### 8.3 Writable recovery of a suspect/rollback-capable image

This remains intentionally fail-closed. `CognitiveStore::open_with_recovery` cannot safely grant a writable owner because the current state layer does not yet have both:

- a descriptor-bound SQLite writer VFS/non-reconnecting connection; and
- an independently current writer fence supplied by the trusted host.

Pathname reopen is not an acceptable substitute because it would weaken TOCTOU/rollback guarantees. The exact closure options and rollback procedure are in [`MIGRATION.md`](MIGRATION.md). Until that primitive is qualified, repository status must keep `writableSuspectImageRecoveryImplemented=false`.

## 9. Migration, cutover and rollback

The current authority convergence is an **ingress cutover**, not a physical database migration. Both predecessor and successor code use the same `cognitive_1.sqlite3`; therefore creating a new database and backfilling it would introduce the dual-authority problem this work removes.

The complete pre-cutover, cutover, rollback, frontier/hash verification and failure rules are in [`MIGRATION.md`](MIGRATION.md). Key rules are:

- one runtime generation writable at a time;
- fence old writer before successor activation;
- preserve exact current recovery witness where host policy requires rollback detection;
- compare memory/source/tombstone/fact/graph frontiers after reopen;
- never restore an old valid backup with ordinary open;
- never dual-write the V2 oracle and SQLite owner.

Schema migrations inside the SQLite owner remain deterministic and transactional under the existing `hepta-memory` migration machinery. A future physical-store migration requires its own off-route transform, count/digest/frontier reconciliation and reverse/forward-compatible rollback plan.

## 10. Integrity and invariant parity

The durable snapshot path validates revision ancestry, latest-head consistency, tombstone non-resurrection, citation presence, verified/time-valid head visibility, source bounds and knowledge-fact/graph frontiers. The semantic V2 oracle separately validates writer fence, intent idempotency, revision chains, tombstone terminality, image checksum and snapshot-key progression.

Parity is enforced at the ownership boundary rather than by keeping two production implementations alive: only SQLite is durable; V2 is qualification-only. The repository authority drift gate additionally checks that the durable fact projection remains tied to `memory_revisions` and that product openers use the façade.

Any future V2 semantic rule promoted to production must be implemented in the one durable path and receive a durable regression test before the status document can claim parity.

## 11. Failure semantics

The store fails closed on missing/invalid authority, scope mismatch, stale expected revision, stale writer generation/fence, conflicting idempotency identity, tombstone resurrection, schema/integrity failure and recovery-currentness uncertainty.

Unknown external-effect outcomes remain `Indeterminate`; they require explicit status/reconciliation. A committed local row is never erased merely because acknowledgement publication failed. A frozen read snapshot is not authority to ignore later revocation/deletion state.

Resource ceilings are bounded. Capacity saturation or an oversized recovery image rejects before unbounded work; it does not create unlimited retry loops.

## 12. Security and privacy

Authority is least-privilege, operation-bound, owner-bound, epoch/fence-bound and independently verified at the production writer seam. The cognitive store does not mint the external grant it consumes. Private payloads remain in owner-local storage; receipts/evidence prefer digests and bounded metadata.

Recovery anchors are integrity/currentness comparison inputs, not signatures and not writer grants. A suspect backup cannot authenticate itself. Immediate revocation/stop requirements remain effective across frozen snapshots.

## 13. Verification commands and source evidence

Focused source tests:

- `codex-rs/hepta-cognitive-store/src/lib_tests.rs` — qualification semantic oracle;
- `codex-rs/hepta-cognitive-store/src/v2_tests.rs` — V2 semantic/fence/image oracle;
- `codex-rs/hepta-cognitive-store/tests/durable_authority.rs` — real SQLite façade reopen and recovery no-fallback;
- `codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs` — durable snapshot/revision/tombstone reopen;
- `codex-rs/hepta-memory/src/production_writer.rs` tests — single writer, restart replay, dispatch crash and concurrency;
- `scripts/test_hepta_cognitive_store_authority.py` — source ownership/drift gate.

From `codex-rs`:

```text
just test -p codex-hepta-cognitive-store -p codex-hepta-memory -p codex-hepta-agentd
```

From repository root:

```text
python3 scripts/hepta_cognitive_store_authority.py
python3 scripts/hepta-implementation-maps.py verify
```

These are invocation identities, not stored pass receipts. Exact-head and deterministic synthetic-merge CI must run on the candidate before `productExecutionProved` changes.

## 14. Observability and operations

Operational identity is one Agent-local SQLite database, `cognitive_1.sqlite3`. Monitor owner/path identity, schema verification, WAL/durability profile, writer lock/lease generation, pending/indeterminate occurrence age, snapshot frontiers, recovery-anchor generation and integrity failures. Do not log private payloads or external authority tokens.

Current operating reference: [`codex-rs/hepta-memory/LANE_C_SQLITE.md`](../../../codex-rs/hepta-memory/LANE_C_SQLITE.md).

## 15. Status and completion boundaries

The canonical repository status is [`STATUS.json`](STATUS.json), and [`IMPLEMENTATION_MAP.json`](IMPLEMENTATION_MAP.json) is verified against it.

Current repository claims are intentionally split:

- source implementation: **yes**;
- durable production implementation exists: **yes**;
- named Agentd product open path composed through `cognitive.store`: **yes**;
- single-writer production mechanism implemented: **yes**;
- real durable reopen source test present: **yes**;
- exact-current-cut cold read recovery present: **yes**;
- writable recovery of a suspect image: **no, fail-closed**;
- exact-candidate product execution proved: **no until CI receipt**;
- independent acceptance: **no**;
- activation/promotion/release: **no**.

Documentation, source implementation, production implementation, candidate execution, independent acceptance and release are different facts. No document may collapse those states.

## 16. Work-package interpretation

Relevant packages remain `MEM-1-STORE` and `MEM-8-PRODUCTION-WRITER`. Historical plan/dossier rows may still describe them as planned envelopes; that planning state is not the live repository implementation status. `STATUS.json` is the single repository-controlled current status source for this module, while readiness/acceptance/release systems remain authoritative for their own external gates.

Future source changes stop on authority violation, base drift, evidence mismatch, cross-owner write, unbounded resource/retry, reintroduction of direct product store opening, or any fallback from failed recovery into unanchored ordinary opening.

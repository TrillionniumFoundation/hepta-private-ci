# cognitive.store production convergence

Status: source candidate implementation plan and qualification contract.

This document fixes the production ownership decision that was previously
ambiguous between `hepta-cognitive-store` and `hepta-memory`.

## 1. Final ownership decision

`codex-hepta-cognitive-store` is the product-facing authoritative owner of the
memory and knowledge-fact domains.

`codex-hepta-memory` remains the physical SQLite durability engine and may own
backend implementation details, migrations, projection tables and local
transaction helpers. It is not a second product-facing cognitive-store
boundary.

The canonical product composition is:

```text
product / agentd / observation
        |
        v
codex-hepta-cognitive-store::ProductionCognitiveStore
        |  authority + writer fence + owner boundary
        v
codex-hepta-memory::CognitiveStore
        |  SQLite WAL/FULL + append-only durable tables
        v
cognitive_1.sqlite3
```

Product code must not acquire a raw durable cognitive backend in order to
perform authoritative writes. Qualification tests may exercise the backend
directly, but those call sites are not production composition evidence.

## 2. Memory and knowledge-fact authority

The durable memory ledger is the append-only `memory_revisions` family plus its
citations and current-head projection.

The durable knowledge-fact ledger is the append-only KG revision family:

- `kg_revision_fact_sets`
- `kg_revision_entities`
- `kg_revision_relations`
- associated immutable citation/count invariants

`MemoryKind::Fact` and the V2 `KnowledgeFactRecordV2`/frontier are semantic
oracle and snapshot representations. They are not a second independently
writable durable fact database. This resolves the previous ambiguity: the
canonical durable fact authority is the SQLite KG revision chain, while V2
fact records are deterministic projections used to verify owner semantics.

## 3. Single-writer rule

A production mutation is legal only when all of the following hold:

1. the caller enters through `ProductionCognitiveStore`;
2. an externally verified `ProductionAuthorityLease` matches the Agent owner;
3. the grant-bound fencing token and authority/owner epochs match;
4. `ProductionDurableWriter` holds the process-lifetime OS writer lock;
5. the active lease head matches the requested generation;
6. the SQLite transaction and append-only revision/CAS invariants succeed.

The lower-level raw-store constructor in Agentd is qualification-only and is
kept solely for existing fixtures. It must not be used by product startup.

## 4. Reopen, recovery and rollback protection

There are two distinct guarantees and they must not be conflated.

### Durable reopen

Ordinary `ProductionCognitiveStore::open` opens/migrates the SQLite store,
verifies required schema/integrity and reconstructs the same durable logical cut.
The owner crate contains a mutate/drop/reopen test that compares exact recovery
anchors before and after reopen.

### Rollback-sensitive recovery admission

`ProductionCognitiveStore::open_with_recovery` delegates to the descriptor-safe
recovery boundary. It never falls back to ordinary open when recovery semantics
were requested. The current `codex-state` backend still intentionally returns
`Unavailable` for writer recovery until a descriptor-backed SQLite VFS,
non-reconnecting writer connection and current writer fence are implemented.

Therefore an exact-current-cut anchor is currently qualification evidence and a
cold-image integrity input, not permission to resume a writer. No document may
claim descriptor-bound writer recovery is complete until that backend exists and
its fault-injection tests pass.

## 5. Legacy-to-owner cutover

The repository currently uses the same `cognitive_1.sqlite3` durable format, so
this convergence does not require copying durable records into a second database.
The migration is a route/authority cutover, not a data duplication migration.

For an existing installation:

1. stop new production cognitive writes;
2. drain local durable outbox work to a recorded watermark;
3. release or expire the old production writer lease;
4. capture an exact recovery anchor and counts/frontiers;
5. verify `memory_revisions`, tombstones, citations, KG revision fact sets,
   entities and relations against their declared invariants;
6. start the new binary with the same durable database and a strictly newer
   externally verified writer generation/epoch;
7. open the writer only through `ProductionCognitiveStore`;
8. capture the post-open anchor and verify that the pre-cutover logical cut is
   unchanged before admitting a new mutation;
9. perform one canary mutation, reopen the store, and verify the new cut;
10. publish the new route/generation only after exact-head and synthetic-merge
    qualification evidence is green.

No dual-write phase is permitted.

## 6. Rollback

Rollback is route based and preserves the same compatible SQLite state:

1. stop the new writer and drain/reconcile known local outcomes;
2. release/rollback its lease and record the terminal lease head;
3. verify the durable cut and schema are readable by the rollback binary;
4. acquire a fresh rollback generation/authority lease; never reuse the old
   active fence;
5. reopen the same durable database through the authoritative owner seam;
6. verify memory/KG counts, tombstones and frontiers before resuming writes.

If schema compatibility is not satisfied, rollback stops. Restoring an old
backup without an independently current witness is forbidden because it can
resurrect deleted or superseded facts.

## 7. Required production qualification

The claim boundary may be raised to `productionImplementation=true` only after
all repository-controlled checks below are green on the exact candidate and its
deterministic base merge:

- `codex-hepta-cognitive-store` package tests, including durable SQLite reopen;
- `codex-hepta-memory` package tests;
- `codex-hepta-agentd` product composition tests;
- strict Clippy/all-target compilation;
- one-process writer exclusion and stale grant/epoch cases;
- real SQLite CAS/concurrent writer tests;
- migration/cutover idempotency and rollback compatibility checks;
- module registry/docs/implementation-map validation.

Descriptor-bound corruption recovery is a separate blocking capability. Until
`codex-state` can safely return an identity-bound durable writer pool, the
recovery claim remains explicitly incomplete even if ordinary durable reopen is
qualified.

## 8. Claim vocabulary

Use these terms consistently:

- **semantic oracle implemented**: V2 invariants exist and are tested;
- **durable owner composed**: product path enters through
  `ProductionCognitiveStore` and uses the SQLite backend;
- **production implementation proved**: exact candidate tests/CI establish the
  composed source implementation;
- **recovery admission proved**: descriptor-bound writer recovery plus current
  witness/fence is tested;
- **activated / accepted / released**: external lifecycle states, never inferred
  from source implementation.

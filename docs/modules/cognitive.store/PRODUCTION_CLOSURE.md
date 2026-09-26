# cognitive.store production convergence

Status: source implementation with independent exact-candidate qualification required; activation and release remain externally governed.

## Unique canonical production-write facade

`codex_hepta_agentd::AgentdProductionWriterHost` is the **unique canonical production-write facade**.  The deleted `ProductionCognitiveStore` file was unreachable from its crate root and is not an API.  The semantic V2 store is a qualification oracle, not a production database.

```text
external trusted host
  | current-cut witness + live authority + generation
  v
AgentdProductionWriterHost
  | sealed ProductionCognitiveMutationCapability
  v
hepta-memory::CognitiveStore
  | BEGIN IMMEDIATE + WAL/FULL + append-only provenance
  v
cognitive_1.sqlite3
```

Normal serving state retains only `DurableCognitiveReadStore`.  Its API exposes snapshots, retrieval observation and revalidation, but no source append, memory mutation, migration, lease creation, writer or raw backend.  The raw writer accessor on the product facade is public only under `qualification-cognitive-write`; the default build keeps it crate-private.

## Authority and linearization

Every production semantic mutation requires an externally verified authority lease, owner/authority epochs, an opaque grant-bound fencing token, a nonzero writer generation, the expected predecessor revision and the final semantic input digest.  Agentd never mints these values.  Admission, source/Memory/fact/projection mutation and committed provenance share one SQLite transaction.  Identical recovery is idempotent; changed semantics conflict; uncertain external dispatch is observer-only reconciliation and never blind replay.

## Recovery and bootstrap

Writable recovery is descriptor-bound and fail-closed.  It acquires the exclusive store fence, copies retained database/WAL/journal descriptors into a private generation, verifies schema, integrity, exact current-cut equality and live production authority, checkpoints, then atomically publishes the active pointer.  Ambiguity after pointer rename is `Indeterminate`.

`tools/cognitive-store-host-bootstrap/bootstrap.py` persists and authenticates the host-side witness bundle, monotone epochs/generation, active-pointer/database digests, canary, revocation and rollback state.  Its HMAC key authenticates host evidence only; it cannot issue production authority and never stores raw fencing tokens.

## Qualification boundary

The dedicated workflow independently runs source-head and deterministic base-merge lanes.  Each command is wrapped by `hepta_ci_exec.py`, bound to exact source/tested SHAs and retained in one machine-readable manifest.  Required commands include package tests, the Agentd product test, ignored crash/reopen probe, 256 and 16,384 record profiles, strict Clippy, architecture verification and bootstrap tests.

A green source workflow proves the tested source implementation only.  Independent semantic review, target-host qualification, operator acceptance, canary promotion, activation and release remain separate.  Tombstone is logical non-use; it is never represented as physical erase, backup deletion, derived-artifact revocation or model unlearning.

# cognitive.store production boundary and closure contract

Status: source convergence in progress; exact-candidate qualification, independent acceptance, activation and release remain separate gates.

This document is the current production-ownership decision for `cognitive.store`. It supersedes the former uncompiled `ProductionCognitiveStore` proposal. The repository has exactly one production write façade: `codex_hepta_agentd::AgentdProductionWriterHost`.

## 1. Canonical ownership

The ownership chain is:

```text
trusted host bootstrap
  signed current-cut witness + live signed authority state + opaque token
        |
        v
codex_hepta_agentd::AgentdProductionWriterHost
  exact-cut recovery + generation fence + sealed mutation capability
        |
        v
codex_hepta_memory::ProductionCognitiveMutationCapability
  live authority revalidation + one BEGIN IMMEDIATE transaction
        |
        v
codex_hepta_memory::CognitiveStore
  physical SQLite owner, WAL/FULL, append-only ledgers and CAS heads
        |
        v
cognitive_1.sqlite3
```

`codex-hepta-cognitive-store` remains the module-level semantic façade and contract export. `codex-hepta-memory` remains the physical SQLite owner. Neither creates a second cognitive database. Agentd is the only product component allowed to assemble the writable owner, recovery proof and externally supplied authority into a serving capability.

The former `src/production.rs` file was not reachable from the crate root, had drifted from the recovery API and created a second nominal façade. It is retired rather than revived. Closed-world verification now fails on any unreferenced top-level Rust source in `hepta-cognitive-store`.

## 2. Compile-time and repository boundary

The raw `hepta-memory::CognitiveStore` alias is not part of the default `codex-hepta-cognitive-store` feature surface. It is available only under:

- `agentd-production-host`, enabled by the named Agentd crate; or
- `qualification-cognitive-write`, which extends the same host feature for explicit qualification fixtures.

This feature gate is reinforced by `scripts/verify_cognitive_store_boundary.py`. The verifier checks:

1. the raw alias remains feature-gated;
2. no orphan source file can silently escape compilation;
3. serving/product roots do not import `hepta-memory::CognitiveStore` directly outside the canonical host;
4. serving/product roots do not call raw semantic mutation methods;
5. `IMPLEMENTATION_MAP.json` contains exactly one `product_writer_host` and binds it to `AgentdProductionWriterHost`.

The physical owner crate may expose internal mutation helpers to its own modules and tests. Qualification fixtures may use explicitly named qualification features. Neither exception is a product call path.

## 3. Authoritative domains

The Memory authority is the append-only source and memory-revision chain in `cognitive_1.sqlite3`, including citations, current heads and tombstones.

The knowledge-fact authority is the immutable `kg_revision_fact_sets`, `kg_revision_entities` and `kg_revision_relations` subledger keyed by the owning `(memory_id, memory_revision)`. Facts have no independent mutable head or writer. A correction publishes a complete successor fact set; a tombstone publishes an empty successor fact set. Rebuildable graph projections never become source authority.

The in-memory V1/V2 store remains a bounded semantic oracle and qualification model. It is not a durability backend and is not a second production writer.

## 4. Production write admission

A production semantic mutation is legal only when all of the following hold:

1. the caller holds an `AgentdProductionWriterHost` created through exact-cut recovery;
2. the current-cut witness was retained and authenticated outside the Agent home rollback domain;
3. the authority lease came from an external signer and matches Agent, grant, epochs, expiry, generation and opaque fencing token;
4. the live verifier rechecks the current signed authority/revocation state immediately before each mutation;
5. the recovered store holds the exclusive process-lifetime store fence;
6. the sealed `ProductionCognitiveMutationCapability` performs remember, correct or forget;
7. admission, source/Memory/fact/projection mutation and terminal committed provenance marker share one `BEGIN IMMEDIATE` transaction;
8. predecessor/revision CAS and all content/provenance digests validate.

Default Agentd startup does not mint a witness, token, grant or verifier. Without explicit trusted-host bootstrap it remains read-only.

## 5. Reopen and rollback-sensitive recovery

Ordinary reopen verifies schema and integrity and reconstructs the committed logical cut. It is suitable for read-only availability but is not rollback-sensitive writer admission.

Writable `open_with_recovery` is a separate fail-closed path. It:

- validates an independently retained exact-current-cut anchor;
- acquires the exclusive cognitive store fence;
- binds existing database/WAL/journal descriptors without following redirections;
- copies bounded bytes into a fresh private generation;
- verifies schema, logical cut and SQLite integrity;
- revalidates external production authority and fencing identity;
- checkpoints and protects the private generation;
- atomically publishes the active-generation pointer.

If pointer publication may have succeeded but directory durability is uncertain, the result is `Indeterminate`. The candidate is not deleted and ordinary open is not used as a fallback. A later trusted recovery ceremony must reconcile the active pointer and retained generation.

## 6. Rotation, restart and revocation

Authority and writer generation are independent monotone values. A new grant, owner epoch, token or writer generation creates a new host generation. Old fences are never reused.

On restart the host must:

1. authenticate the latest current-cut witness and signer trust;
2. authenticate the current authority state and token binding;
3. reject revoked, expired, regressed or predecessor-inconsistent authority state;
4. recover the exact cut;
5. run owner reconciliation before opening admission;
6. retain `Indeterminate` outcomes for observer-only settlement rather than blind replay.

Live revocation is checked before every semantic write. Revocation after an operation has crossed its committed transaction boundary does not rewrite historical truth; it prevents later writes.

## 7. Canary and rollback generation

A canary is a normal capability-bound semantic mutation with a deterministic source identity and an explicit expected predecessor. It must produce a committed production receipt, survive reopen and appear in the exact next cut. A cleanup tombstone is a second normal mutation and is not physical erasure.

Rollback is route- and generation-based. It must use a newly signed authority state with a strictly newer writer generation and a fresh grant-bound fence. The rollback binary must prove schema compatibility and the exact durable cut before it admits writes. Reusing a prior generation, token or stale witness is forbidden.

## 8. Qualification contract

`productionImplementation` may become true only after terminal-success evidence is retained for the same exact source candidate and deterministic base merge:

- `codex-hepta-cognitive-store` tests;
- `codex-hepta-memory` tests;
- Agentd cognitive product-writer tests;
- child-process crash/reopen qualification;
- 256-record and 16,384-record durable performance profiles;
- all-target strict Clippy;
- architecture/orphan verification;
- machine-readable command and evidence manifests;
- clean tracked source.

Target-host bootstrap, canary, rollback, latency and fault-injection receipts are separate from repository source qualification. Independent semantic review, operator acceptance, promotion and release remain external lifecycle decisions.

## 9. Claim vocabulary

Use the following terms exactly:

- **semantic source implemented**: the bounded V2 state machine and validation rules exist in source;
- **durable owner source implemented**: the SQLite owner, migrations and transaction paths exist;
- **canonical product façade source implemented**: Agentd is the sole mapped production write host and raw product bypass checks pass;
- **bootstrap source implemented**: signed external witness/authority loading and live verifier exist, without claiming deployment configuration;
- **product execution proved**: exact candidate and deterministic merge evidence are terminal-success and retained;
- **target-host qualified**: bootstrap, canary, restart, rollback, performance and fault injection passed on the selected host profile;
- **activated / accepted / promoted / released**: externally governed states never inferred from source implementation.

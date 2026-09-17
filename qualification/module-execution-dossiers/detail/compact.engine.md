# compact.engine: implementation design

Parent: `docs/modules/compact.engine/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: canonical deletion-aware checkpoint construction, semantic payload budgeting, evaluator-attributed qualification, and Agent-local durable publication/reload are implemented. Exact-head execution, independent semantic acceptance, activation, promotion and release remain evidence gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-compact-engine`.
Packages: `MEM-5-COMPACT`.
Integration owner: `codex-rs/hepta-memory` remains the sole authoritative writer for the Agent-local cognitive SQLite store.

The native engine owns pure construction and proof contracts. Durable publication is deliberately composed through the existing cognitive owner store rather than creating another database, authority verifier, or execution spine.

## 2. Public operations and contract details

The implemented checkpoint surface is:

`build_qualified_candidate(source_snapshot, generation, predecessor, policy, semantic_artifact, inputs) -> QualifiedCompactionCandidateV2`; `prove_compaction(candidate, qualification) -> QualifiedCompactionProofV2`; `CognitiveStore::compact_and_publish_authorized(authority, verifier, ...) -> (candidate, proof, published)`; `CognitiveStore::load_current_compact_checkpoint(scope) -> validated checkpoint/proof/artifact/payload`.

The former public `compact() -> CompactCheckpoint` shortcut is retired. `CompactCheckpointV1` is the single canonical checkpoint contract. No checkpoint operation overwrites source facts, admits a semantic summary as a source fact, or treats qualification evidence as deployment authority.

Replay scheduling and skill induction remain separate target capabilities; they are not implied by checkpoint construction or publication.

## 3. State records and transaction design

`CompactCheckpointV1` binds the coherent Lane C snapshot, support manifest, semantic compaction algorithm, compressed payload digest, omitted-information digest, tombstone cutoff, compatibility and predecessor digest. `QualifiedCompactionCandidateV2` additionally binds the retention manifest, semantic artifact, retained live records, omission set and loss report.

The semantic artifact binds producer identity, exact source snapshot, model, tokenizer, semantic algorithm, payload digest, byte count and token count. Its contract is authority-free and explicitly cannot be admitted as a source fact.

Durable publication is owned by `hepta-memory` migration `0011_canonical_compact_checkpoints.sql`. Immutable generation rows contain the complete serialized checkpoint/proof/artifact bundle plus the exact payload bytes and authority provenance. A separate current-head row is foreign-key bound to the exact `(scope, generation, checkpoint_digest)` generation.

Publication uses one `BEGIN IMMEDIATE` transaction. Generation 1 requires no predecessor. Later generations require `generation == current + 1` and `predecessor_digest == current checkpoint digest`. The immutable generation is inserted before a compare-and-swap head advance; either both become durable or the transaction rolls back. Replay of the exact same bundle is idempotent; reuse of a checkpoint identity/digest with changed proof, artifact or payload conflicts.

## 4. Deterministic algorithm and semantic compaction boundary

Input lineages are grouped by stable memory identity, ordered by revision, required to start at revision 1 and advance one revision at a time with exact predecessor digests. A live revision after any tombstone is rejected as resurrection. Tombstoned heads are excluded from retained context. Policy-protected identities must be present in the supplied snapshot and protected live heads are selected before optional heads. Optional heads are ordered by retention priority and stable identity, giving input-order-independent output.

The engine does not silently invent summaries. Semantic compression is an explicit upstream responsibility represented by `SemanticCompactionArtifactV1`. The engine verifies that artifact against the same source snapshot, model, tokenizer and registered semantic algorithm and binds its payload digest into the canonical checkpoint. This separates semantic generation from retention/checkpoint authority while preserving an auditable digest chain.

## 5. Capacity and performance profile

Native hard ceilings are 65,536 compaction inputs and 4,096 protected references. A policy additionally supplies non-zero `maximum_payload_bytes` and `maximum_payload_tokens`, bounded by engine-wide maxima of 16 MiB and 1,048,576 tokens. The policy tokenizer digest must equal the snapshot tokenizer digest, and the semantic artifact's exact byte/token accounting must fit both policy bounds before checkpoint construction.

The source tests include a 10,000-record build/publish/reload fixture. This is a bounded regression fixture, not a latency/SLO measurement. Product performance claims still require target-host benchmark receipts.

## 6. Qualification and proof provenance

`CompactionQualificationV2` binds an evaluator stable identity, evaluator implementation digest, evaluation artifact digest, retained-query suite digest, reconstruction obligation digest, contradiction holdout digest, attestation digest, attestation-key digest and signature digest. All retained-query, reconstruction, contradiction-preservation and deletion-non-resurrection obligations must pass.

`QualifiedCompactionProofV2` wraps the canonical Lane C `CompactionProofV1` and a digest-bound `CompactionEvaluatorEvidenceV1`; its own proof digest binds both. The engine therefore no longer discards evaluator identity/attestation provenance after accepting qualification results. Cryptographic signature verification remains an external independent-verifier responsibility; the compact engine records and binds the verifier evidence but does not self-authorize or self-accept.

## 7. Durable reload, corruption handling and rollback

Every reload joins the selected head to its immutable generation, deserializes the bundle, reconstructs the Lane C snapshot, canonical checkpoint, semantic artifact, base proof and qualified proof, reruns all contract validations, recomputes the payload SHA-256 from stored bytes, verifies the exact byte count and compares every durable digest column. Any mismatch fails closed as store corruption.

A restart reopens the same cognitive SQLite store and selects the current validated head. A construction or publication crash before the head CAS retains the predecessor generation; an injected fault after generation insertion is covered by a transaction-rollback test. Concurrent generation publication is serialized by SQLite and the head CAS leaves exactly one winner. Rollback is generation selection/revalidation; it never restores deleted source facts.

## 8. Current implementation and evidence boundary

- **Implemented entrypoints:** `build_qualified_candidate` in [codex-rs/hepta-compact-engine/src/qualified.rs](../../../codex-rs/hepta-compact-engine/src/qualified.rs); `prove_compaction` in [codex-rs/hepta-compact-engine/src/qualified.rs](../../../codex-rs/hepta-compact-engine/src/qualified.rs).
- **Production caller:** `compact_and_publish_authorized` in [codex-rs/hepta-memory/src/canonical_compaction_store.rs](../../../codex-rs/hepta-memory/src/canonical_compaction_store.rs).
- **Durable owner/reload:** `CognitiveStore` owns publication and `load_current_compact_checkpoint`; migration [0011_canonical_compact_checkpoints.sql](../../../codex-rs/hepta-memory/migrations/0011_canonical_compact_checkpoints.sql) creates immutable generations and the selected head.
- **Source tests:** [codex-rs/hepta-compact-engine/src/qualified_tests.rs](../../../codex-rs/hepta-compact-engine/src/qualified_tests.rs), [codex-rs/hepta-compact-engine/src/lib_tests.rs](../../../codex-rs/hepta-compact-engine/src/lib_tests.rs), and the in-module E2E/fault/concurrency/corruption/large-batch tests in [canonical_compaction_store.rs](../../../codex-rs/hepta-memory/src/canonical_compaction_store.rs). These test identities are not substitutes for exact-head execution receipts.
- **Implemented checkpoint closure:** one canonical checkpoint API; non-resurrection on the only construction path; semantic byte/token budgets and tokenizer/model binding; evaluator/attestation provenance; atomic publication; CAS generation advance; reload/corruption validation; restart recovery; production authority verifier integration.
- **Remaining external gates:** exact-head and merge-candidate test receipts, independent semantic review/attestation verification, target-host performance qualification, operator acceptance, canary, promotion and release.
- **Separate future capabilities:** replay scheduling and skill induction are still separate work and do not change the checkpoint subsystem claim boundary.

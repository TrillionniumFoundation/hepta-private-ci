# memory.retrieval: implementation design

Parent: `docs/modules/memory.retrieval/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: owner-bound pre-top-k generation, policy-relative completeness, bounded HNMF recall, final source revalidation and delivery-aware causal assignment are implemented as a source candidate. Exact-head/synthetic-merge CI, target-host measurements and independent acceptance remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-memory-retrieval`.
Packages: `MEM-2-RETRIEVAL`.

The module remains a read-only deterministic decision component. The durable SQLite owner stays in `codex-hepta-memory`; the durable assignment writer stays in `learning.ledger`; Agentd is an explicit opt-in composition host. No implementation here creates a second memory store, artifact registry, learning writer or execution spine.

## 2. Public operations and contract details

The target flow is now represented by native source operations:

`compile_cue(objective, approved_context, request, snapshot) -> MemoryCueV1`; owner generators produce bounded `RetrievalGeneratorBatchV1` values; `build_candidate_union_from_generated(cue, policy, input) -> GeneratedCandidateUnionV1`; `recall_generated_with_engram(cue, policy, input, engram_snapshot, dynamics_policy) -> GeneratedRecallV1`; and `observe_retrieval_assignment(...)` binds the generator-relative enumerated, legal and selected sets for the learning-ledger owner.

The channel vocabulary is lexical, vector, entity, graph, temporal, causal, procedural and contradiction support. A positive-weight policy channel must have exactly one corresponding generator-owner batch. Missing or unexpected policy channels fail closed. The current SQLite owner supplies lexical, entity, graph and temporal observations. Vector, causal, procedural and contradiction-support channels are not claimed until their actual owners supply authenticated batches.

## 3. State records and transaction design

The retrieval core owns no source facts and no durable cache. Inputs bind the exact Lane C generation vector, cue/profile, generator identity and generation, source-completeness state, retrieval policy and engram generation. Public receipts remain `DENY_ALL` authority.

`CognitiveStore::observe_memory_retrieval` generates and revalidates the SQLite-owned bounded candidate universe in one read transaction before legacy top-four truncation. The adapter preserves exact memory revision, content/source support, per-channel rank and saturation state. Final content is materialized only after the selected identities are revalidated again against the owner.

Causal assignment facts are appended only by `learning.ledger`. They distinguish the full enumerated set, deterministic legal set, HNMF-selected set and the final delivered subset after downstream response limits, NDU planning and final owner/currentness checks. An optional learned reranker is a separate downstream policy; its propensity cannot be inferred from the HNMF deterministic propensity.

## 4. Deterministic algorithm and scheduling

Generator batches are canonicalized independently of completion order. Total raw candidate events are bounded before union. Exact record revision deduplication and per-channel truncation precede weighted union. Zero-weight channels cannot satisfy coverage.

The HNMF core expands only the supplied immutable local engram generation, settles for at most four steps, applies per-population sparse competition, records activation paths and resource counts, detects contradictions, and returns recall or an explicit abstention. Public receipt validators re-check structural invariants in addition to digest equality, so mutating a public receipt and recomputing its digest is insufficient to cross the boundary.

The production candidate does not treat vector similarity as truth and does not average contradictory facts. Current source support is revalidated before content leaves the owner boundary.

## 5. Capacity and performance profile

Enforced product ceilings are:

- at most 512 total generator candidate events before union;
- at most 16 recall selections;
- at most 4096 engram nodes;
- at most 32768 synapses;
- at most four settling steps;
- at most 64 active units per population.

The SQLite owner currently observes up to four channels with at most 32 rows per channel before deduplication. A channel reports `Exhausted` or `LimitReached`; generator-relative incompleteness is preserved rather than rewritten as complete recall.

These are code-enforced capacity bounds, not target-host performance claims. p50/p95/p99 latency, throughput, CPU, RSS/peak memory, allocation, SQLite busy/WAL behavior and source-revalidation cost require a named host, compiler/profile, fixture, data size and observation interval. CI timing or a simulator run cannot be promoted into those claims.

## 6. Concrete verification cases

- **RET-01 — deterministic union:** channel/generator permutation produces the same canonical union and recall packet. Source: `generation_bound_tests.rs` and `generator_tests.rs`.
- **RET-02 — contradiction safety:** contradictory active support forces explicit abstention where policy requires it. Source: `generation_bound_tests.rs` and `engram_tests.rs`.
- **RET-03 — current support before delivery:** the owner adapter binds exact revision/support and Agentd performs final batch revalidation before materialization; stale or revoked support is omitted or fails closed. Source: `cognitive_retrieval_adapter_tests.rs`, `cognitive_context_hnmf_tests.rs` and existing cognitive revalidation tests.
- **RET-04 — independent ablations:** plain/no-intervention, lexical-only, no-recurrence and no-inhibition baselines have explicit deterministic fixtures. Source: `engram_tests.rs` and generator/retrieval tests. These fixtures establish separable interventions and resource receipts; they do not establish longitudinal task utility without independently observed outcomes.

Additional negative coverage includes oversized total generator input, channel-rank mismatch, policy/generator coverage mismatch, cross-generation receipt rebinding, recomputed malformed receipt forgeries, tombstones, duplicate identities, OOD and stale generation.

Test identities are not execution receipts. Exact-head and ordered-parent synthetic-merge runs must be inspected before the source candidate advances.

## 7. Integration, rollback and capability ceiling

The opt-in Agentd context path can consume an authenticated `CurrentMemoryRetrievalContext`. With that context present it obtains the owner read cut, observes the complete bounded pre-top-four generator output, executes HNMF recall, optionally applies the separately selected learned reranker to the HNMF-selected set, packs the bounded response, runs NDU context planning, revalidates the Lane C cut/retrieval context/ranker, and records the final delivered subset through the durable learning-ledger owner when configured.

The ordinary CLI does not synthesize a retrieval generation, engram or learned model. A missing/revoked current context fails closed rather than silently falling back to stale HNMF state. Compatibility retrieval remains available when no HNMF currentness source is explicitly composed; that compatibility path is not evidence for the new policy.

Rollback removes the optional current-context/learning attachments and restores the compatible owner retrieval path. Cached or restored answers may not bypass current tombstones or revision revalidation.

Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge, self-selection or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `retrieve_v2` in [codex-rs/hepta-memory-retrieval/src/v2.rs](../../../codex-rs/hepta-memory-retrieval/src/v2.rs); `compile_cue` and `build_candidate_union_from_generated` in [codex-rs/hepta-memory-retrieval/src/generator.rs](../../../codex-rs/hepta-memory-retrieval/src/generator.rs); `recall_generated_with_engram` in [codex-rs/hepta-memory-retrieval/src/generator.rs](../../../codex-rs/hepta-memory-retrieval/src/generator.rs); `settle_engram` in [codex-rs/hepta-memory-retrieval/src/engram.rs](../../../codex-rs/hepta-memory-retrieval/src/engram.rs); `observe_retrieval_assignment` in [codex-rs/hepta-memory-retrieval/src/decision.rs](../../../codex-rs/hepta-memory-retrieval/src/decision.rs). Owner-bound generation, policy-relative completeness, HNMF recall and causal assignment observations are implemented as native source candidates.
- **Owner composition:** [codex-rs/hepta-memory/src/cognitive_retrieval_adapter.rs](../../../codex-rs/hepta-memory/src/cognitive_retrieval_adapter.rs) converts one SQLite owner observation into canonical generator batches without accepting caller-authored source scores. [codex-rs/hepta-agentd/src/cognitive_context.rs](../../../codex-rs/hepta-agentd/src/cognitive_context.rs) is the explicit product-host candidate and ranks before legacy top-four truncation.
- **State and recovery:** retrieval/HNMF ranking is stateless. Existing `hepta-memory` SQLite remains the content/index owner. `learning.ledger` owns durable assignment evidence and now binds the final delivered subset separately from HNMF selection.
- **Source tests:** [generation_bound_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs), [generator_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/generator_tests.rs), [engram_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/engram_tests.rs), [decision_tests.rs](../../../codex-rs/hepta-memory-retrieval/src/decision_tests.rs), [cognitive_retrieval_adapter_tests.rs](../../../codex-rs/hepta-memory/src/cognitive_retrieval_adapter_tests.rs), [cognitive_context_hnmf_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_hnmf_tests.rs), and learning-ledger retrieval/durable tests. These are source identities, not pass receipts for the current draft head.
- **Qualification path:** `.github/workflows/hepta-consolidated-source.yml` already runs exact source and synthetic/base-merge package tests, formatting and strict all-target Clippy for the relevant packages. Lane E/converged-learning gates additionally exercise the durable causal owner.
- **Remaining repository-controlled work:** obtain green exact-head and synthetic-merge execution receipts for this candidate and fix any surfaced regressions. Keep the implementation map at `productionImplementation=false`, `productExecutionProved=false`, `activation=false` and `release=false` until those claims have their required evidence.
- **Remaining external/owner work:** supply and qualify actual vector/causal/procedural/contradiction generators if those channels are enabled; independently observe downstream learned-ranker propensities/outcomes; run named target-host p50/p95/p99, throughput, CPU/RSS/allocation and large-store measurements; complete independent semantic acceptance, canary, promotion and release.

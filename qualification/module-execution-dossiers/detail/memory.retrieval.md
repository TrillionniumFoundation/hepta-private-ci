# memory.retrieval: implementation design

Parent: `docs/modules/memory.retrieval/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: owner-backed pre-top-four generation, cue/channel binding, bounded HNMF recall and explicit Agentd host composition are implemented. Target-host qualification, independent efficacy/semantic acceptance, activation, promotion and release remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`.

## 1. Source and work envelope

Roots: `codex-rs/hepta-memory-retrieval`.
Package: `MEM-2-RETRIEVAL`.

The engine owns no source-fact database and no deployment authority. The existing `hepta-memory::CognitiveStore` remains the SQLite content/index owner; Agentd is the explicit product-host adapter; `learning.ledger` remains the causal-decision owner.

## 2. Public operations and contract details

Implemented native operations are `compile_cue`, `build_candidate_union`, `build_candidate_union_from_batches`, `expand_candidate_engram`, `recall` and `recall_with_engram`, with compatibility `retrieve_v2`.

`MemoryCueV1` binds objective, approved context, cue profile and one exact `CognitiveSnapshotKeyV1`. `RetrievalChannelBatchV1` makes generator coverage explicit as exhausted, truncated or partial. Candidate union and recall receipts bind cue/policy/generation, exact record revision/digest, channel/support evidence, omissions and deny-all authority.

The channel vocabulary is lexical, vector, entity, temporal, causal, procedural and contradiction-support. The current SQLite owner adapter maps only evidence it actually owns: MemoryFts→lexical, EntityFts→entity and Recency→temporal. GraphOneHop is deliberately not reinterpreted as causal/procedural. A requested channel without an authenticated owner batch fails closed.

## 3. State records and transaction design

The retrieval engine is stateless. `CognitiveStore::observe_memory_retrieval` generates and revalidates the owner's bounded pool in one SQLite read transaction before the legacy top-four projection. It retains per-channel rank, source-revision revalidation bindings and channel saturation observations.

Agentd intersects that pool with one authoritative `ReadRequestV2` result by exact record ID, revision and content digest. The host supplies an immutable retrieval profile/generation vector and optional pinned learned ranker. Final context byte planning and all owner/profile/ranker revalidation complete before causal-decision append.

The causal sink stores the complete legal candidate set plus explicit `abstain` and the actual assignment propensity in the canonical `learning.ledger`. `DurableMemoryRetrievalDecisionSink` only wraps a host-authorized, already-created/recovered `DurableLedger`; it owns no path, credential or witness service.

## 4. Deterministic algorithm and scheduling

1. Compile a generation-bound cue.
2. Acquire explicit bounded channel batches from actual owners.
3. Canonicalize by channel/rank/exact revision; enforce per-channel limits and completeness.
4. Stable-union and exact-revision deduplicate with policy weights.
5. Expand a candidate-local engram neighborhood for at most four hops.
6. Build inbound adjacency once, then run bounded recurrent settling and per-population sparse competition.
7. Detect contradiction/OOD/coverage/score abstention conditions.
8. Return at most 16 exact-revision selections.
9. Optionally apply the host-pinned learned ranker only to admitted selections.
10. Apply final context byte/NDU planning; revalidate the SQLite cut, retrieval profile and learned artifact; only then append the causal decision.

`recurrent_steps=0` is the no-recurrence ablation. `inhibition_enabled=false` is the no-inhibition ablation; inhibitory edges are ignored, never converted to excitatory support. Vector similarity alone never proves truth.

## 5. Capacity and performance profile

Engine ceilings are <=512 candidate events, <=4096 local nodes, <=32768 synapses, <=4 settling steps, <=16 recall selections and <=64 active units per population.

The physical SQLite owner is currently stricter: each MemoryFts/EntityFts/GraphOneHop/Recency generator returns at most 32 rows; the owner observation materializes at most 128 revalidated candidates. That stricter owner bound remains authoritative until separately qualified.

`.github/workflows/hepta-memory-retrieval-qualification.yml` executes a maximum-profile deterministic source candidate for exact head and synthetic merge, retains p50/p95/p99 wall latency plus process CPU/RSS observations and validates the structural ceilings. Those measurements describe the CI host only. Target-host latency/resource SLOs and longitudinal task quality require independent evidence.

## 6. Concrete verification cases

- RET-01: generation-bound permutation tests prove channel completion order cannot change the canonical union/recall.
- RET-02: HNMF contradiction fixtures force explicit abstention.
- RET-03: SQLite correction/withdrawal/revalidation tests, Agentd final cut revalidation and product tombstone-after-reopen coverage prevent stale source attachment.
- RET-04: lexical-only policy plus explicit no-recurrence and no-inhibition dynamics are executable ablation profiles. A no-intervention baseline is the product path that does not attach retrieval. Independent utility/resource comparison remains a learning/evaluation responsibility, not something the retrieval engine may self-score.

The 512-record SQLite saturation fixture proves the physical generator remains bounded on a larger store. Durable-ledger recovery proves 512 legal candidates plus explicit abstain fit and reopen under the event bound.

## 7. Integration, rollback and capability ceiling

`AgentdConfig` can be given a host-selected `PinnedMemoryRetrievalRuntime`; normal configuration does not invent a profile or activate one implicitly. The composed read path stays read-only with respect to cognitive facts. Optional learned ranking is additive and its artifact ID is bound into a compound policy identity for causal logging.

Rollback removes the explicit runtime/ranker attachment or restores a compatible immutable profile; the next request always rebuilds from current SQLite tombstones/revisions. Cached answers are not restored as truth.

Immediate revocation/stop remains effective across frozen snapshots. No source or qualification fixture self-issues operator activation, independent acceptance, promotion or release.

## 8. Current native implementation

- **Engine entrypoints:** `retrieve_v2` (`src/v2.rs`); `compile_cue`, `build_candidate_union`, `recall` (`src/generation_bound.rs`); `build_candidate_union_from_batches` (`src/channel_contract.rs`); `expand_candidate_engram` (`src/engram_expansion.rs`); `recall_with_engram` (`src/hnmf.rs`).
- **Owner generation:** `CognitiveStore::observe_memory_retrieval` in `codex-rs/hepta-memory` exposes the bounded pre-top-four materialized pool and exact revalidation facts without changing the legacy top-four API.
- **Product composition:** Agentd `owner_retrieval_adapter`, `PinnedMemoryRetrievalRuntime` and `cognitive_context::read_with_runtime` bind the owner cut to the engine before final result truncation. `PinnedCognitiveRanker` may reorder only after HNMF admission.
- **Causal persistence:** `DurableMemoryRetrievalDecisionSink` appends the complete legal set/propensity to the canonical durable learning ledger after final context planning and revalidation. Equal retries are idempotent; same identity/different semantics conflicts.
- **Receipt validation:** public union/recall/HNMF receipts re-check canonical ordering, limits, record liveness/digests, scores, generation identity, deny-all authority and computed receipt digests rather than trusting builder provenance.
- **Source qualification:** focused tests cover permutation/property-style invariance, explicit completeness, 512/513 bounds, local engram expansion, recurrent/inhibition ablations, 512-record SQLite saturation and durable reopen. The source qualification workflow retains exact-head and synthetic-merge CI-host performance/resource observations.
- **Remaining repository capability gaps:** vector, causal, procedural and contradiction-support channels still require their actual owners to expose authenticated bounded batches. Unsupported configured channels intentionally fail closed.
- **Remaining external gates:** independent task/recall-quality evaluation, longitudinal ablations, target-host CPU/RSS/latency qualification, operator acceptance, activation, canary, promotion and release.

# MEM-1 owner integration audit

Audit date: 2026-11-08. Live product integration: **HOLD**.
This change supplies a native kernel and 70-run reference protocol, not an active Agentd owner.
A local adapter or a passing SQLite fixture is not a product loop.

## Existing owner APIs

The SQLite owner is `codex-rs/hepta-memory`. Its `Cargo.toml` already depends on
`codex-hepta-memory-retrieval`; a local read adapter needs no new dependency.

In [`lane_c_snapshot.rs`](../../codex-rs/hepta-memory/src/lane_c_snapshot.rs):

```rust
pub async fn lane_c_snapshot(&self, access: &CognitiveAccess, scope: &CognitiveScope,
    now_unix_seconds: i64) -> Result<DurableCognitiveSnapshot, CognitiveStoreError>;
pub fn bind_context(&self, vector: LaneCGenerationVectorV1,
    acquired_at_unix_ms: u64, lease_expires_unix_ms: u64)
    -> Result<AuthoritativeSnapshotV1, SnapshotProviderError>;
pub async fn revalidate_lane_c_snapshot(&self, access: &CognitiveAccess, scope: &CognitiveScope, expected: &DurableCognitiveSnapshot,
    now_unix_seconds: i64) -> Result<DurableCognitiveSnapshot, CognitiveStoreError>;
```

`bind_context` belongs to `DurableCognitiveSnapshot`; the others belong to `CognitiveStore`.
It checks owner scope/frontiers and the observation lease. Obtain this opaque cut from
the store and bind authenticated external model/encoder/prompt/authority context.
Do not mint an authoritative snapshot in a runner.

In [`cognitive_retrieval_observation.rs`](../../codex-rs/hepta-memory/src/cognitive_retrieval_observation.rs)
and [`cognitive_retrieval.rs`](../../codex-rs/hepta-memory/src/cognitive_retrieval.rs):

```rust
pub async fn observe_memory_retrieval(&self, access: &CognitiveAccess,
    request: &RetrievalRequest) -> Result<RetrievalObservation, CognitiveStoreError>;
pub async fn revalidate_memory_candidates(&self, access: &CognitiveAccess, bindings: &[MemoryRevalidationBinding], now_unix_seconds: i64)
    -> Result<Vec<RevalidationStatus>, CognitiveStoreError>;
```

In [`cognitive_retrieval_adapter.rs`](../../codex-rs/hepta-memory/src/cognitive_retrieval_adapter.rs):

```rust
pub fn execute_owner_observation(observation: &RetrievalObservation, cut: &DurableCognitiveSnapshot, context: &RetrievalExecutionContextV1,
    request_digest: Digest32, acquired_at_unix_ms: u64, lease_expires_unix_ms: u64)
    -> Result<OwnerRetrievalExecutionV1, CognitiveStoreError>;
```

## Existing caller and missing provider

[`state_control.rs`](../../codex-rs/hepta-agentd/src/state_control.rs), in `AgentdMethod::CognitiveContext`, calls
`read_with_retrieval_context_and_learning` in [`cognitive_context.rs`](../../codex-rs/hepta-agentd/src/cognitive_context.rs).
It obtains the owner cut/observation, executes HNMF, optionally permutes selected records,
and revalidates records, owner cut and external context before publication.
Raw content is materialized after ordering.

The external provider signature in `hepta-agentd/src/cognitive_retrieval_context.rs` is
`fn current(&self, owner: &AgentId, body_generation: u64) -> Result<RetrievalExecutionContextV1, String>`.
The bounded repository search was:

```sh
rg -n 'impl .*CurrentMemoryRetrievalContext|CurrentMemoryRetrievalContext for|with_cognitive_retrieval_context\(' codex-rs tools scripts qualification -g '*.rs' -g '*.py' -g '*.md'
```

The only implementation found is `SwitchingContext` in `codex-rs/hepta-agentd/src/cognitive_context_hnmf_tests.rs`;
the other hit is `AgentdConfig::with_cognitive_retrieval_context` in `config.rs`.
`AgentdConfig::from_process_environment` selects the profile but supplies no provider.
`runtime.rs::require_cognitive_retrieval_context_for_mode` rejects HNMF-required startup without a context.
The search does not exclude an out-of-repository embedding.

## Smallest safe next integration

1. Retain `execute_owner_observation` and its HNMF selection/abstention unchanged.
2. Call `FastMemoryV1::predict` with the snapshot key returned by `cut.bind_context`.
3. Obtain encoder-owned features for exact selected ID/revision/content identities;
   check shape, finite values, encoder identity and complete selected-set coverage.
4. Reorder only that set; retain batch record, owner-cut and external-context final
   revalidation and delivered-subset accounting.
5. Do not replace HNMF with `FastMemoryV1::rerank`: its fresh plain recall can choose
   a different set from the existing engram path.

A roughly 100-line adapter can exercise SQLite reads and prediction, but cannot activate
the caller: `PinnedCognitiveRanker` in `hepta-agentd/src/cognitive_ranker.rs` loads selected
tabular artifacts, not a private fast-memory owner.

## Remaining ownership work

- Fast state: a Cell owner, current witness, writer fencing, bounded checkpoint/recovery/reset,
  encoder supply and Agentd attachment. `hepta-memory/src/shared_experience.rs` provides
  `read_shared_experience` / `revalidate_shared_experience`; updates need Replay, not Recall.
- Slow knowledge: a real trainer/adapter candidate, independent evaluation, current dataset eligibility,
  `hepta-learning-artifacts` selection/revocation owners, then verified successor consumption or `NoUpdate`.
- Acceptance: actual host/provider integration, post-revocation final use and full owner crash recovery.
  Synthetic owner checks do not close these gates.

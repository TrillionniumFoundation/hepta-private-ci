use super::*;

use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::RetrievalRequest;
use codex_hepta_memory::SourceDraft;
use codex_hepta_memory_retrieval::RetrievalChannelV1;
use codex_hepta_paths::HeptaFleetRoot;

#[tokio::test]
async fn real_sqlite_observation_adapts_to_canonical_retrieval_batches() {
    let temp = tempfile::tempdir().unwrap();
    let fleet = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet).unwrap();
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000119").unwrap();
    let layout = HeptaFleetRoot::parse(fleet).unwrap().layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await.unwrap();
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "adapter-source".to_string(),
                content: b"verified lemon owner adapter".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await
        .unwrap();
    store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "adapter-memory".to_string(),
                revision: MemoryRevisionDraft {
                    scope: scope.clone(),
                    content: "verified lemon owner adapter".to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: vec![citation],
                },
            },
        )
        .await
        .unwrap();

    let cut = store.lane_c_snapshot(&access, &scope, 100).await.unwrap();
    let observation = store
        .observe_memory_retrieval(&access, &RetrievalRequest::new("lemon", 100))
        .await
        .unwrap();
    let generation = Digest32::of_bytes(b"externally-frozen-generation-vector");
    let batches =
        adapt_sqlite_owner_observation(&cut.snapshot().records, &observation, generation).unwrap();

    assert_eq!(batches.len(), 3);
    let lexical = batches
        .iter()
        .find(|batch| batch.channel == RetrievalChannelV1::Lexical)
        .unwrap();
    assert_eq!(lexical.candidates.len(), 1);
    assert_eq!(lexical.candidates[0].channel_rank, 1);
    assert_eq!(lexical.candidates[0].generation_vector_digest, generation);
    assert!(!lexical.candidates[0].support_digest.is_zero());

    let temporal = batches
        .iter()
        .find(|batch| batch.channel == RetrievalChannelV1::Temporal)
        .unwrap();
    assert_eq!(temporal.candidates.len(), 1);
}

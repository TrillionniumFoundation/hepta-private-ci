use super::*;

use codex_hepta_cognitive_read::ReadRequest;
use codex_hepta_cognitive_read::ReadRequestV2;
use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::KgEntityFactDraft;
use codex_hepta_memory::KgFactSetDraft;
use codex_hepta_memory::KgRelationFactDraft;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::RetrievalRequest;
use codex_hepta_memory::SourceDraft;
use codex_hepta_memory_retrieval::RetrievalChannelV1;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn owner_observation_adapts_to_engine_channels_without_free_scores() {
    let directory = tempfile::tempdir().expect("tempdir");
    let fleet = directory.path().join("fleet");
    std::fs::create_dir(&fleet).expect("fleet directory");
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000151").expect("owner");
    let layout = HeptaFleetRoot::parse(fleet)
        .expect("fleet root")
        .layout()
        .agent(&owner);
    let store = CognitiveStore::open(&layout).await.expect("store");
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "adapter-source".to_string(),
                content: b"Ada studied the analytical engine.".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await
        .expect("source");
    store
        .remember_with_kg(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "adapter-memory-source".to_string(),
                content: b"Ada studied the analytical engine.".to_vec(),
                observed_at_unix_seconds: 100,
            },
            &MemoryDraft {
                stable_key: "adapter-ada".to_string(),
                revision: MemoryRevisionDraft {
                    scope: scope.clone(),
                    content: "Ada studied the analytical engine.".to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: vec![citation],
                },
            },
            &KgFactSetDraft {
                entities: vec![
                    KgEntityFactDraft {
                        key: "ada".to_string(),
                        entity_type: "person".to_string(),
                        label: "Ada".to_string(),
                    },
                    KgEntityFactDraft {
                        key: "engine".to_string(),
                        entity_type: "machine".to_string(),
                        label: "Analytical Engine".to_string(),
                    },
                ],
                relations: vec![KgRelationFactDraft {
                    key: "studied".to_string(),
                    from_entity_key: "ada".to_string(),
                    to_entity_key: "engine".to_string(),
                    relation: "studied".to_string(),
                }],
            },
        )
        .await
        .expect("memory");

    let cut = store
        .lane_c_snapshot(&access, &scope, /*now_unix_seconds*/ 200)
        .await
        .expect("cut");
    let read = cut
        .read(ReadRequestV2 {
            read_request: ReadRequest {
                snapshot_digest: cut.snapshot().snapshot_digest,
                allowed_kinds: Vec::new(),
                maximum_results: 1024,
                include_tombstones: false,
            },
            maximum_encoded_bytes: 1024 * 1024,
        })
        .expect("read");
    let observation = store
        .observe_memory_retrieval(
            &access,
            &RetrievalRequest::new("Ada", /*now_unix_seconds*/ 200),
        )
        .await
        .expect("observation");
    let generation_vector_digest = Digest32::of_bytes(b"adapter-generation-vector");
    let batches =
        adapt_owner_retrieval(&observation, &read, generation_vector_digest).expect("adapter");

    assert_eq!(
        batches
            .iter()
            .map(|batch| batch.channel)
            .collect::<Vec<_>>(),
        vec![
            RetrievalChannelV1::Lexical,
            RetrievalChannelV1::Entity,
            RetrievalChannelV1::Temporal,
        ]
    );
    for batch in &batches {
        batch.validate().expect("valid engine batch");
        assert!(
            batch
                .candidates
                .iter()
                .all(|candidate| candidate.generation_vector_digest == generation_vector_digest)
        );
    }

    let entity = batches
        .iter()
        .find(|batch| batch.channel == RetrievalChannelV1::Entity)
        .expect("entity batch");
    assert_eq!(entity.candidates.len(), 1);
    assert_eq!(entity.candidates[0].channel_rank, 1);
    assert_eq!(entity.candidates[0].ood, ProbabilityQ32::ONE);
    assert!(!entity.candidates[0].support_digest.is_zero());
}

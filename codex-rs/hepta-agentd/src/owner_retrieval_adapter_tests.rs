use super::*;

use codex_hepta_cognitive_read::AuthoritativeCognitiveSnapshotProvider;
use codex_hepta_cognitive_read::AuthoritativeSnapshotV1;
use codex_hepta_cognitive_read::ReadRequest;
use codex_hepta_cognitive_read::ReadRequestV2;
use codex_hepta_cognitive_read::SnapshotAcquisitionRequestV1;
use codex_hepta_cognitive_read::SnapshotProviderError;
use codex_hepta_cognitive_read::read_authoritative;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
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
use codex_hepta_memory_retrieval::RetrievalChannelWeightV1;
use codex_hepta_memory_retrieval::build_candidate_union_from_batches;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[derive(Clone)]
struct Provider(AuthoritativeSnapshotV1);

impl AuthoritativeCognitiveSnapshotProvider for Provider {
    fn acquire(
        &self,
        _request: &SnapshotAcquisitionRequestV1,
    ) -> Result<AuthoritativeSnapshotV1, SnapshotProviderError> {
        Ok(self.0.clone())
    }
}

#[tokio::test]
async fn sqlite_owner_observation_maps_without_fabricating_graph_semantics() {
    let directory = tempfile::tempdir().unwrap();
    let fleet = directory.path().join("fleet");
    std::fs::create_dir(&fleet).unwrap();
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
                content: b"lemon owner observation".to_vec(),
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
                    content: "lemon owner observation".to_string(),
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

    let cut = store.lane_c_snapshot(&access, &scope, 200).await.unwrap();
    let frontiers = cut.frontiers();
    let vector = LaneCGenerationVectorV1 {
        scope_id: cut.scope_id().clone(),
        purpose_id: id("purpose:owner-retrieval"),
        memory_ledger_frontier: frontiers.memory,
        knowledge_fact_frontier: frontiers.knowledge_facts,
        tombstone_frontier: frontiers.tombstone,
        source_ledger_frontier: frontiers.source,
        knowledge_graph_generation: frontiers.knowledge_graph,
        compact_checkpoint_generation: Generation::new(1).unwrap(),
        prompt_registry_revision: Revision::new(1).unwrap(),
        retrieval_profile_digest: digest("retrieval-profile"),
        encoder_preprocessor_digest: digest("encoder-profile"),
        authority_epoch: 1,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
    };
    let authoritative = cut.bind_context(vector, 200_000, 210_000).unwrap();
    let snapshot_key = authoritative.snapshot_key().clone();
    let provider = Provider(authoritative);
    let read = read_authoritative(
        &provider,
        200_001,
        SnapshotAcquisitionRequestV1 {
            request_id: id("request:owner-retrieval"),
            scope_id: cut.scope_id().clone(),
            purpose_id: id("purpose:owner-retrieval"),
            minimum_memory_frontier: frontiers.memory,
            minimum_tombstone_frontier: frontiers.tombstone,
            authority_epoch: 1,
            deadline_unix_ms: 205_000,
        },
        ReadRequestV2 {
            read_request: ReadRequest {
                snapshot_digest: cut.snapshot().snapshot_digest,
                allowed_kinds: Vec::new(),
                maximum_results: 512,
                include_tombstones: false,
            },
            maximum_encoded_bytes: 1024 * 1024,
        },
    )
    .unwrap();
    let observation = store
        .observe_memory_retrieval(&access, &RetrievalRequest::new("lemon", 200))
        .await
        .unwrap();
    let cue = codex_hepta_memory_retrieval::compile_cue(
        id("cue:owner-retrieval"),
        digest("objective"),
        digest("approved-context"),
        snapshot_key,
        digest("cue-profile"),
    )
    .unwrap();
    let policy = RetrievalPolicyV1 {
        policy_id: id("policy:owner-retrieval"),
        channel_weights: vec![
            RetrievalChannelWeightV1 {
                channel: RetrievalChannelV1::Lexical,
                weight: FixedQ32::ONE,
                maximum_candidates: 32,
            },
            RetrievalChannelWeightV1 {
                channel: RetrievalChannelV1::Entity,
                weight: FixedQ32::ONE,
                maximum_candidates: 32,
            },
            RetrievalChannelWeightV1 {
                channel: RetrievalChannelV1::Temporal,
                weight: FixedQ32::ONE,
                maximum_candidates: 32,
            },
        ],
        maximum_results: 4,
        minimum_total_score: FixedQ32::ZERO,
        maximum_ood: ProbabilityQ32::ONE,
        minimum_distinct_channels: 1,
        abstain_on_contradiction: false,
    };
    let batches = adapt_owner_retrieval(&cue, &policy, &read, &observation).unwrap();
    assert_eq!(batches.len(), 3);
    assert!(batches.iter().all(|batch| batch.channel != RetrievalChannelV1::Causal));
    let union = build_candidate_union_from_batches(&cue, &policy, batches).unwrap();
    assert!(!union.union.entries.is_empty());
    union.validate().unwrap();

    let mut unsupported = policy;
    unsupported.channel_weights.push(RetrievalChannelWeightV1 {
        channel: RetrievalChannelV1::Causal,
        weight: FixedQ32::ONE,
        maximum_candidates: 32,
    });
    assert!(
        adapt_owner_retrieval(&cue, &unsupported, &read, &observation)
            .unwrap_err()
            .contains("cannot prove channel semantics")
    );
}

use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
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
use codex_hepta_memory_retrieval::EngramNodeV1;
use codex_hepta_memory_retrieval::EngramSnapshotV1;
use codex_hepta_memory_retrieval::RecallDynamicsV1;
use codex_hepta_memory_retrieval::RetrievalChannelV1;
use codex_hepta_memory_retrieval::RetrievalChannelWeightV1;
use codex_hepta_memory_retrieval::RetrievalPolicyV1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
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

struct CurrentProfile {
    revision: Mutex<u64>,
}

impl CurrentMemoryRetrievalProfile for CurrentProfile {
    fn current(
        &self,
        preparation: &MemoryRetrievalPreparationV1,
    ) -> Result<MemoryRetrievalProfileV1, String> {
        let revision = *self.revision.lock().map_err(|_| "lock poisoned")?;
        let vector = LaneCGenerationVectorV1 {
            scope_id: preparation.scope_id.clone(),
            purpose_id: id("purpose:runtime-recall"),
            memory_ledger_frontier: preparation.memory_ledger_frontier,
            knowledge_fact_frontier: preparation.knowledge_fact_frontier,
            tombstone_frontier: preparation.tombstone_frontier,
            source_ledger_frontier: preparation.source_ledger_frontier,
            knowledge_graph_generation: preparation.knowledge_graph_generation,
            compact_checkpoint_generation: Generation::new(1).unwrap(),
            prompt_registry_revision: Revision::new(revision).unwrap(),
            retrieval_profile_digest: digest("retrieval-profile"),
            encoder_preprocessor_digest: digest("encoder-profile"),
            authority_epoch: 1,
            model_digest: digest("model"),
            tokenizer_digest: digest("tokenizer"),
            template_digest: digest("template"),
            tool_schema_digest: digest("tools"),
        };
        let key = CognitiveSnapshotKeyV1::new(vector.clone()).map_err(|error| error.to_string())?;
        Ok(MemoryRetrievalProfileV1 {
            vector,
            cue_id: id("cue:runtime"),
            objective_digest: digest("objective"),
            approved_context_digest: digest("context"),
            cue_profile_digest: digest("cue-profile"),
            policy: RetrievalPolicyV1 {
                policy_id: id("policy:runtime"),
                channel_weights: vec![
                    RetrievalChannelWeightV1 {
                        channel: RetrievalChannelV1::Lexical,
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
            },
            engram: EngramSnapshotV1 {
                generation_vector_digest: key.vector_digest,
                nodes: preparation
                    .candidates
                    .iter()
                    .map(|candidate| EngramNodeV1 {
                        record_id: id(&candidate.record_id),
                        population_id: id("population:runtime"),
                        cue_bias: FixedQ32::ZERO,
                        threshold: FixedQ32::ZERO,
                    })
                    .collect(),
                synapses: Vec::new(),
            },
            dynamics: RecallDynamicsV1 {
                recurrent_steps: 1,
                maximum_active_units_per_population: 64,
                leak: FixedQ32::ZERO,
            },
        })
    }
}

#[tokio::test]
async fn runtime_binds_owner_cut_and_detects_profile_change() {
    let directory = tempfile::tempdir().unwrap();
    let fleet = directory.path().join("fleet");
    std::fs::create_dir(&fleet).unwrap();
    let owner =
        codex_hepta_contracts::AgentId::parse("00000000-0000-4000-8000-000000000119").unwrap();
    let layout = HeptaFleetRoot::parse(fleet).unwrap().layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await.unwrap();
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "runtime-profile-source".to_string(),
                content: b"runtime lemon memory".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await
        .unwrap();
    store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "runtime-profile-memory".to_string(),
                revision: MemoryRevisionDraft {
                    scope: scope.clone(),
                    content: "runtime lemon memory".to_string(),
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
    let observation = store
        .observe_memory_retrieval(&access, &RetrievalRequest::new("lemon", 200))
        .await
        .unwrap();

    let current = Arc::new(CurrentProfile {
        revision: Mutex::new(1),
    });
    let runtime =
        PinnedMemoryRetrievalRuntime::new(owner.clone(), 1, current.clone()).unwrap();
    let prepared = runtime
        .prepare(&owner, 1, "lemon", &cut, &observation)
        .unwrap();
    assert_eq!(
        prepared.preparation.candidates.len(),
        observation.materialized_candidates().len()
    );
    runtime.revalidate(&prepared).unwrap();

    *current.revision.lock().unwrap() = 2;
    assert!(
        runtime
            .revalidate(&prepared)
            .unwrap_err()
            .contains("changed during request")
    );
}

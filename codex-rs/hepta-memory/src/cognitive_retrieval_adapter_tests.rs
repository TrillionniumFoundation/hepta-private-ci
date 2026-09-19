use super::*;

use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_memory_retrieval::EngramDynamicsPolicyV1;
use codex_hepta_memory_retrieval::EngramSnapshotV1;
use codex_hepta_memory_retrieval::RetrievalGeneratorOwnerV1;
use codex_hepta_memory_retrieval::compile_cue;
use codex_hepta_memory_retrieval::recall_generated;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use tempfile::TempDir;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::DurableCognitiveSnapshot;
use crate::KgFactSetDraft;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryVerification;
use crate::RetrievalRequest;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::source;

fn vector(cut: &DurableCognitiveSnapshot) -> LaneCGenerationVectorV1 {
    let digest = Digest32::of_bytes(b"retrieval-adapter-test-profile");
    LaneCGenerationVectorV1 {
        scope_id: cut.scope_id().clone(),
        purpose_id: StableId::new("purpose:owner-retrieval-test").unwrap(),
        memory_ledger_frontier: cut.frontiers().memory,
        source_ledger_frontier: cut.frontiers().source,
        tombstone_frontier: cut.frontiers().tombstone,
        knowledge_fact_frontier: cut.frontiers().knowledge_facts,
        knowledge_graph_generation: cut.frontiers().knowledge_graph,
        compact_checkpoint_generation: Generation::new(1).unwrap(),
        prompt_registry_revision: Revision::new(1).unwrap(),
        retrieval_profile_digest: digest,
        encoder_preprocessor_digest: digest,
        authority_epoch: 1,
        model_digest: digest,
        tokenizer_digest: digest,
        template_digest: digest,
        tool_schema_digest: digest,
    }
}

fn revision(content: &str) -> MemoryRevisionDraft {
    MemoryRevisionDraft {
        scope: CognitiveScope::AgentPrivate,
        content: content.to_string(),
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: 100,
        valid_to_unix_seconds: None,
        citations: Vec::new(),
    }
}

#[tokio::test]
async fn execution_context_rejects_retrieval_profile_drift() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(60);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;
    let cut = store
        .lane_c_snapshot(&access, &scope, 200)
        .await
        .expect("cut");
    let generation_vector = vector(&cut);
    let vector_digest = generation_vector.digest();
    let context = RetrievalExecutionContextV1 {
        generation_vector,
        objective_digest: Digest32::of_bytes(b"objective"),
        approved_context_digest: cut.snapshot().snapshot_digest,
        cue_profile_digest: sqlite_owner_cue_profile_digest(),
        retrieval_policy: sqlite_owner_retrieval_policy_v1().expect("policy"),
        engram_snapshot: EngramSnapshotV1::new(
            vector_digest,
            Digest32::of_bytes(b"engram-generation"),
            Vec::new(),
            Vec::new(),
        )
        .expect("engram"),
        dynamics_policy: EngramDynamicsPolicyV1::product_default().expect("dynamics"),
    };
    assert!(matches!(
        context.validate(),
        Err(CognitiveStoreError::Conflict(_))
    ));
}

#[tokio::test]
async fn owner_adapter_exposes_pre_top_four_bounded_candidates() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(61);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let access = CognitiveAccess::agent_private(owner);
    for index in 0..20 {
        let draft = revision("Beacon supported fact.");
        store
            .remember_with_kg(
                &access,
                &source(
                    CognitiveScope::AgentPrivate,
                    &format!("source-{index}"),
                    &draft.content,
                ),
                &MemoryDraft {
                    stable_key: format!("beacon-{index}"),
                    revision: draft,
                },
                &KgFactSetDraft::default(),
            )
            .await
            .expect("seed");
    }

    let scope = CognitiveScope::AgentPrivate;
    let cut = store
        .lane_c_snapshot(&access, &scope, 200)
        .await
        .expect("cut");
    let snapshot_key = CognitiveSnapshotKeyV1::new(vector(&cut)).expect("snapshot key");
    let observation = store
        .observe_memory_retrieval(&access, &RetrievalRequest::new("Beacon", 200))
        .await
        .expect("observation");
    assert_eq!(observation.batch().candidates.len(), 4);
    assert!(observation.candidates().len() > 4);

    let generated =
        generated_input_from_owner_observation(&observation, &snapshot_key, cut.snapshot())
            .expect("generated input");
    assert_eq!(generated.batches.len(), 4);
    assert!(
        generated
            .batches
            .iter()
            .any(|batch| batch.receipt.generator == RetrievalGeneratorOwnerV1::CognitiveLexical)
    );
    assert!(
        generated
            .batches
            .iter()
            .any(|batch| batch.receipt.generator == RetrievalGeneratorOwnerV1::CognitiveTemporal)
    );
    assert!(generated.flattened_candidates().expect("flatten").len() > 4);

    let cue = compile_cue(
        StableId::new("cue:owner-adapter-test").unwrap(),
        Digest32::of_bytes(b"retrieve verified owner memory"),
        cut.snapshot().snapshot_digest,
        Digest32::of_bytes(b"Beacon"),
        snapshot_key,
        sqlite_owner_cue_profile_digest(),
    )
    .expect("cue");
    let policy = sqlite_owner_retrieval_policy_v1().expect("policy");
    let recalled = recall_generated(&cue, &policy, &generated).expect("recall");
    assert!(recalled.packet.selections.len() > 4);
    assert!(recalled.packet.selections.len() <= 16);
}

#[tokio::test]
async fn owner_adapter_rejects_observation_from_a_different_cut() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(62);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let access = CognitiveAccess::agent_private(owner);
    let draft = revision("Beacon original.");
    let receipt = store
        .remember_with_kg(
            &access,
            &source(CognitiveScope::AgentPrivate, "source", &draft.content),
            &MemoryDraft {
                stable_key: "beacon".to_string(),
                revision: draft,
            },
            &KgFactSetDraft::default(),
        )
        .await
        .expect("seed");
    let scope = CognitiveScope::AgentPrivate;
    let cut = store
        .lane_c_snapshot(&access, &scope, 200)
        .await
        .expect("cut");

    let corrected = revision("Beacon corrected.");
    store
        .correct_with_kg(
            &access,
            &receipt.memory.id.memory_id,
            receipt.memory.id.revision,
            &source(
                CognitiveScope::AgentPrivate,
                "correction-source",
                &corrected.content,
            ),
            &corrected,
            &KgFactSetDraft::default(),
        )
        .await
        .expect("correct");

    let observation = store
        .observe_memory_retrieval(&access, &RetrievalRequest::new("Beacon", 200))
        .await
        .expect("new observation");
    let snapshot_key = CognitiveSnapshotKeyV1::new(vector(&cut)).expect("old snapshot key");
    assert!(matches!(
        generated_input_from_owner_observation(&observation, &snapshot_key, cut.snapshot()),
        Err(CognitiveStoreError::Conflict(_))
    ));
}

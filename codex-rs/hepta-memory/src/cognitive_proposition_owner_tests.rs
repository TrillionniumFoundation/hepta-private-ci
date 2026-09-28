//! Real SQLite owner -> observation -> HNMF -> assignment regression source.

use super::*;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::KgEntityFactDraft;
use crate::KgFactSetDraft;
use crate::KgRelationFactDraft;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryVerification;
use crate::RetrievalRequest;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::source;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_memory_retrieval::EngramDynamicsPolicyV1;
use codex_hepta_memory_retrieval::EngramNodeV1;
use codex_hepta_memory_retrieval::EngramPopulationV1;
use codex_hepta_memory_retrieval::EngramSnapshotV1;
use codex_hepta_memory_retrieval::EngramSupportV1;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use tempfile::TempDir;

fn revision(text: &str) -> MemoryRevisionDraft {
    MemoryRevisionDraft {
        scope: CognitiveScope::AgentPrivate,
        content: text.to_string(),
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: 100,
        valid_to_unix_seconds: None,
        citations: Vec::new(),
    }
}
fn facts() -> KgFactSetDraft {
    KgFactSetDraft {
        entities: ["alpha", "beta"]
            .into_iter()
            .map(|key| KgEntityFactDraft {
                key: key.to_string(),
                entity_type: "concept".to_string(),
                label: key.to_string(),
            })
            .collect(),
        relations: vec![KgRelationFactDraft {
            key: "assertion".to_string(),
            from_entity_key: "alpha".to_string(),
            to_entity_key: "beta".to_string(),
            relation: "supports".to_string(),
        }],
    }
}
async fn execute(store: &CognitiveStore, access: &CognitiveAccess) -> OwnerRetrievalExecutionV1 {
    let cut = store
        .lane_c_snapshot(access, &CognitiveScope::AgentPrivate, 200)
        .await
        .expect("cut");
    let observation = store
        .observe_memory_retrieval(access, &RetrievalRequest::new("Beacon", 200))
        .await
        .expect("observe");
    let policy = sqlite_owner_retrieval_policy_v1().expect("policy");
    let external = Digest32::of_bytes(b"explicit-test-owner-generation");
    let vector = LaneCGenerationVectorV1 {
        scope_id: cut.scope_id().clone(),
        purpose_id: StableId::new("purpose:assertion-test").expect("purpose"),
        memory_ledger_frontier: cut.frontiers().memory,
        source_ledger_frontier: cut.frontiers().source,
        tombstone_frontier: cut.frontiers().tombstone,
        knowledge_fact_frontier: cut.frontiers().knowledge_facts,
        knowledge_graph_generation: cut.frontiers().knowledge_graph,
        compact_checkpoint_generation: Generation::new(1).expect("generation"),
        prompt_registry_revision: Revision::new(1).expect("revision"),
        retrieval_profile_digest: policy.digest(),
        encoder_preprocessor_digest: external,
        authority_epoch: 1,
        model_digest: external,
        tokenizer_digest: external,
        template_digest: external,
        tool_schema_digest: external,
    };
    let nodes = observation
        .candidates()
        .iter()
        .enumerate()
        .map(|(index, candidate)| EngramNodeV1 {
            node_id: StableId::new(format!("node:{index}")).expect("node"),
            population: EngramPopulationV1::SemanticConcept,
            support: vec![EngramSupportV1 {
                record_id: StableId::new(candidate.revalidation.memory.memory_id.as_str())
                    .expect("record"),
                record_revision: Revision::new(candidate.revalidation.memory.revision)
                    .expect("revision"),
            }],
            threshold: FixedQ32::ZERO,
            confidence: ProbabilityQ32::ONE,
            generation_vector_digest: vector.digest(),
        })
        .collect();
    let graph = EngramSnapshotV1::new(vector.digest(), external, nodes, Vec::new()).expect("graph");
    let mut dynamics = EngramDynamicsPolicyV1::product_default().expect("dynamics");
    dynamics.minimum_activation = FixedQ32::ZERO;
    dynamics.lateral_inhibition = FixedQ32::ZERO;
    let context = RetrievalExecutionContextV1 {
        generation_vector: vector,
        objective_digest: external,
        approved_context_digest: cut.snapshot().snapshot_digest,
        cue_profile_digest: sqlite_owner_cue_profile_digest(),
        retrieval_policy: policy,
        engram_snapshot: graph,
        dynamics_policy: dynamics,
    };
    execute_owner_observation(
        &observation,
        &cut,
        &context,
        Digest32::of_bytes(b"Beacon"),
        200_000,
        205_000,
    )
    .expect("owner execution")
}

#[tokio::test]
async fn sqlite_opposite_assertions_abstain_and_correction_removes_old_polarity() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(71);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let access = CognitiveAccess::agent_private(owner);
    let affirmative = facts();
    for (key, negative) in [("positive", false), ("negative", true)] {
        let draft = revision(&format!("Beacon {key} assertion."));
        let mut input = affirmative.clone();
        let denied = if negative {
            std::mem::take(&mut input.relations)
        } else {
            Vec::new()
        };
        store
            .remember_with_assertions(
                &access,
                &source(CognitiveScope::AgentPrivate, key, &draft.content),
                &MemoryDraft {
                    stable_key: key.to_string(),
                    revision: draft,
                },
                &input,
                &denied,
            )
            .await
            .expect("persist assertions");
    }
    let before = execute(&store, &access).await;
    assert_eq!(
        before.recall.packet.disposition,
        RecallDispositionV1::Abstained(RecallAbstentionReasonV1::ContradictoryEvidence)
    );
    assert!(before.assignment.selected_candidates.is_empty());
    let observed = store
        .observe_memory_retrieval(&access, &RetrievalRequest::new("Beacon", 200))
        .await
        .expect("observe");
    assert_eq!(observed.proposition_evidence_digests().len(), 2);
    let negative = observed
        .batch()
        .candidates
        .iter()
        .find(|candidate| candidate.memory.content.contains("negative"))
        .expect("negative");
    let corrected = revision("Beacon corrected affirmative assertion.");
    store
        .correct_with_assertions(
            &access,
            &negative.memory.id.memory_id,
            1,
            &source(
                CognitiveScope::AgentPrivate,
                "corrected",
                &corrected.content,
            ),
            &corrected,
            &affirmative,
            &[],
        )
        .await
        .expect("correct exact old revision");
    let after = execute(&store, &access).await;
    assert_eq!(
        after.recall.packet.disposition,
        RecallDispositionV1::Recalled
    );
    assert_eq!(after.assignment.selected_candidates.len(), 2);
}

#[tokio::test]
async fn legacy_predicate_labels_are_not_reinterpreted_as_assertions() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(72);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let access = CognitiveAccess::agent_private(owner);
    let draft = revision("Beacon legacy label.");
    let mut input = facts();
    input.relations[0].relation = format!("hepta_denied_v2:{}", Digest32::of_bytes(b"supports"));
    store
        .remember_with_kg(
            &access,
            &source(CognitiveScope::AgentPrivate, "legacy", &draft.content),
            &MemoryDraft {
                stable_key: "legacy".to_string(),
                revision: draft,
            },
            &input,
        )
        .await
        .expect("legacy writer");
    let observation = store
        .observe_memory_retrieval(&access, &RetrievalRequest::new("Beacon", 200))
        .await
        .expect("observe");
    assert!(observation.proposition_evidence_digests().is_empty());
}

#[tokio::test]
async fn every_assertion_of_a_multi_claim_revision_is_considered() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(73);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let access = CognitiveAccess::agent_private(owner);
    let mut positive = facts();
    let mut second = positive.relations[0].clone();
    second.key = "second".to_string();
    second.relation = "contains".to_string();
    positive.relations.push(second.clone());
    let draft = revision("Beacon has multiple explicit assertions.");
    store
        .remember_with_assertions(
            &access,
            &source(CognitiveScope::AgentPrivate, "multi", &draft.content),
            &MemoryDraft {
                stable_key: "multi".to_string(),
                revision: draft,
            },
            &positive,
            &[],
        )
        .await
        .expect("multiple");
    positive.relations.clear();
    let draft = revision("Beacon denies the second assertion.");
    store
        .remember_with_assertions(
            &access,
            &source(CognitiveScope::AgentPrivate, "denial", &draft.content),
            &MemoryDraft {
                stable_key: "denial".to_string(),
                revision: draft,
            },
            &positive,
            &[second],
        )
        .await
        .expect("denial");
    let result = execute(&store, &access).await;
    assert_eq!(
        result.recall.packet.disposition,
        RecallDispositionV1::Abstained(RecallAbstentionReasonV1::ContradictoryEvidence)
    );
}

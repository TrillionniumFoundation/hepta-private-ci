use super::*;
use codex_hepta_memory_retrieval::ContradictionPolarityV1;
use codex_hepta_memory_retrieval::RecallAbstentionReasonV1;
use codex_hepta_memory_retrieval::RecallDispositionV1;

async fn seed_statement(store: &CognitiveStore, access: &CognitiveAccess, key: &str, stance: &str) {
    let draft = revision("Beacon statement with explicit owner provenance.");
    store.remember_with_kg(
        access,
        &source(CognitiveScope::AgentPrivate, key, &draft.content),
        &MemoryDraft { stable_key: key.to_string(), revision: draft },
        &KgFactSetDraft {
            entities: vec![
                KgEntityFactDraft { key: "witness".to_string(), entity_type: "source".to_string(), label: "Beacon witness".to_string() },
                KgEntityFactDraft { key: "claim".to_string(), entity_type: "proposition".to_string(), label: "Beacon claim".to_string() },
            ],
            relations: vec![KgRelationFactDraft {
                key: "statement-stance".to_string(), from_entity_key: "witness".to_string(),
                to_entity_key: "claim".to_string(), relation: stance.to_string(),
            }],
        },
    ).await.expect("durable statement");
}

#[tokio::test]
async fn sqlite_same_side_statements_survive_multiple_channels() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(71);
    let store = CognitiveStore::open(&layout(&temp, &owner)).await.expect("store");
    let access = CognitiveAccess::agent_private(owner);
    seed_statement(&store, &access, "statement-a", "supports_proposition").await;
    seed_statement(&store, &access, "statement-b", "supports_proposition").await;
    let cut = store.lane_c_snapshot(&access, &CognitiveScope::AgentPrivate, 200).await.expect("cut");
    let key = CognitiveSnapshotKeyV1::new(vector(&cut)).expect("key");
    let observation = store.observe_memory_retrieval(&access, &RetrievalRequest::new("Beacon", 200)).await.expect("observation");
    assert_eq!(observation.candidates().len(), 2);
    let evidence = &observation.candidates()[0].contradiction_evidence;
    assert_eq!(evidence.len(), 1);
    assert_eq!(evidence[0].polarity, ContradictionPolarityV1::Supports);
    assert_eq!(evidence, &observation.candidates()[1].contradiction_evidence);
    let input = generated_input_from_owner_observation(&observation, &key, cut.snapshot()).expect("input");
    for candidate in input.batches.iter().flat_map(|batch| &batch.candidates) {
        assert_eq!(&candidate.contradiction_evidence, evidence);
        assert!(candidate.contradiction_group_digest.is_none());
    }
    let cue = compile_cue(StableId::new("cue:sqlite-explicit").expect("cue"),
        Digest32::of_bytes(b"objective"), cut.snapshot().snapshot_digest,
        Digest32::of_bytes(b"Beacon"), key, sqlite_owner_cue_profile_digest()).expect("cue");
    let packet = recall_generated(&cue, &sqlite_owner_retrieval_policy_v1().expect("policy"), &input).expect("recall");
    assert_eq!(packet.packet.disposition, RecallDispositionV1::Recalled);
    assert_eq!(packet.packet.selections.len(), 2);
}

#[tokio::test]
async fn sqlite_opposite_statements_force_explicit_abstention() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(72);
    let store = CognitiveStore::open(&layout(&temp, &owner)).await.expect("store");
    let access = CognitiveAccess::agent_private(owner);
    seed_statement(&store, &access, "statement-a", "supports_proposition").await;
    seed_statement(&store, &access, "statement-b", "opposes_proposition").await;
    let cut = store.lane_c_snapshot(&access, &CognitiveScope::AgentPrivate, 200).await.expect("cut");
    let key = CognitiveSnapshotKeyV1::new(vector(&cut)).expect("key");
    let observation = store.observe_memory_retrieval(&access, &RetrievalRequest::new("Beacon", 200)).await.expect("observation");
    assert_eq!(observation.candidates().len(), 2);
    let first = observation.candidates()[0].contradiction_evidence[0];
    let second = observation.candidates()[1].contradiction_evidence[0];
    assert_eq!(first.proposition_digest, second.proposition_digest);
    assert_ne!(first.polarity, second.polarity);
    let input = generated_input_from_owner_observation(&observation, &key, cut.snapshot()).expect("input");
    let cue = compile_cue(StableId::new("cue:sqlite-opposite").expect("cue"),
        Digest32::of_bytes(b"objective"), cut.snapshot().snapshot_digest,
        Digest32::of_bytes(b"Beacon"), key, sqlite_owner_cue_profile_digest()).expect("cue");
    let recall = recall_generated(&cue, &sqlite_owner_retrieval_policy_v1().expect("policy"), &input).expect("recall");
    assert_eq!(recall.packet.disposition, RecallDispositionV1::Abstained(RecallAbstentionReasonV1::ContradictoryEvidence));
}

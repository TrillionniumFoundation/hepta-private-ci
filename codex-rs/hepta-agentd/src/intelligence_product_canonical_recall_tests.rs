use super::*;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf_learning::RecallAbstainReasonV1;
use codex_hepta_cognitive_types::hnmf_learning::RecallPacketV1;
use codex_hepta_cognitive_types::hnmf_learning::RecallResourceReceiptV1;
use codex_hepta_cognitive_types::hnmf_learning::SelectedEventRefV1;
use codex_hepta_intelligence::bind_canonical_recall_for_intelligence_v1;

pub(super) fn explicit_absence_recall(
    run_id: StableId,
) -> CanonicalRecallIntelligenceInputV1 {
    let packet = RecallPacketV1 {
        cue_digest: ContractDigestV1::from_digest(digest("explicit absence cue"))
            .expect("cue digest"),
        event_snapshot_digest: ContractDigestV1::from_digest(digest(
            "explicit absence memory cut",
        ))
        .expect("event snapshot digest"),
        engram_snapshot_digest: ContractDigestV1::from_digest(digest(
            "explicit absence engram cut",
        ))
        .expect("engram snapshot digest"),
        selected_events: Vec::new(),
        active_nodes: Vec::new(),
        activation_paths: Vec::new(),
        contradictions: Vec::new(),
        coverage_ppm: 0,
        confidence_ppm: 0,
        ood_ppm: 0,
        abstain: Some(RecallAbstainReasonV1::NoCandidate),
        resource_receipt: RecallResourceReceiptV1 {
            candidate_event_count: 0,
            node_count: 0,
            synapse_count: 0,
            active_node_count: 0,
            settling_steps: 0,
        },
    };
    bind_canonical_recall_for_intelligence_v1(
        run_id,
        packet,
        Some(digest("legacy explicit absence packet")),
    )
    .expect("explicit canonical absence")
}

fn canonical_context() -> (
    AgentdOwnerPortsV1,
    CanonicalPortInputV1,
    CanonicalRecallIntelligenceInputV1,
) {
    let mut fixture = fixture();
    let event_digest = ContractDigestV1::from_digest(digest("canonical event")).expect("digest");
    let packet = RecallPacketV1 {
        cue_digest: ContractDigestV1::from_digest(digest("cue")).expect("cue"),
        event_snapshot_digest: ContractDigestV1::from_digest(digest("memory cut")).expect("cut"),
        engram_snapshot_digest: ContractDigestV1::from_digest(digest("engram cut")).expect("cut"),
        selected_events: vec![SelectedEventRefV1 {
            event_id: ContractIdV1::new("event:context").expect("id"),
            revision: 1,
            event_digest,
        }],
        active_nodes: Vec::new(),
        activation_paths: Vec::new(),
        contradictions: Vec::new(),
        coverage_ppm: 1_000_000,
        confidence_ppm: 900_000,
        ood_ppm: 0,
        abstain: None,
        resource_receipt: RecallResourceReceiptV1 {
            candidate_event_count: 1,
            node_count: 0,
            synapse_count: 0,
            active_node_count: 0,
            settling_steps: 0,
        },
    };
    fixture.inputs.context_request.items.push(ContextItem {
        item_id: id("event:context"),
        role: ContextRole::UntrustedEvidence,
        content_digest: digest("materialized evidence"),
        source_digest: event_digest.digest(),
        token_count: 2,
        contains_secret: false,
    });
    let input = CanonicalPortInputV1 {
        run_id: fixture.request.run_id.clone(),
        snapshot_digest: fixture.request.snapshot.digest(),
        objective_digest: fixture.request.snapshot.objective_digest(),
        candidate_set_digest: digest("candidate set"),
        predecessor_digest: digest("canonical recall predecessor"),
        budget_micros: 10_000_000,
        stage: CanonicalStageV1::ContextCompiled,
    };
    let recall = bind_canonical_recall_for_intelligence_v1(
        fixture.request.run_id,
        packet,
        Some(digest("legacy recall packet")),
    )
    .expect("recall");
    (AgentdOwnerPortsV1::new(fixture.inputs, None), input, recall)
}

#[test]
fn explicit_abstention_is_a_valid_canonical_retrieval_result() {
    let recall = explicit_absence_recall(id("run:explicit-absence"));
    recall.validate().expect("valid canonical abstention");
    assert!(recall.packet.abstain.is_some());
    assert!(recall.packet.selected_events.is_empty());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn missing_canonical_recall_result_fails_before_owner_use() {
    let mut fixture = fixture();
    fixture.inputs.canonical_recall = None;
    let directory = tempfile::tempdir().expect("directory");
    let runner = AgentdIntelligenceProductRunnerV1::new(
        directory.path().join("unused-authority.json"),
        authority_verifier(),
    )
    .expect("runner");
    let result = runner
        .prepare(&product_test_coordinator(), fixture.request, fixture.inputs)
        .await;
    match result {
        Err(AgentdIntelligenceProductError::Canonical(
            CanonicalIntelligenceError::CanonicalRecall(message),
        )) => assert!(
            message.contains("requires an explicit canonical recall result"),
            "unexpected rejection: {message}"
        ),
        other => panic!("missing canonical recall must fail closed: {other:?}"),
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn canonical_abstention_from_another_run_fails_before_owner_use() {
    let mut fixture = fixture();
    fixture.inputs.canonical_recall = Some(explicit_absence_recall(id("run:other")));
    let directory = tempfile::tempdir().expect("directory");
    let runner = AgentdIntelligenceProductRunnerV1::new(
        directory.path().join("unused-authority.json"),
        authority_verifier(),
    )
    .expect("runner");
    assert!(matches!(
        runner
            .prepare(&product_test_coordinator(), fixture.request, fixture.inputs)
            .await,
        Err(AgentdIntelligenceProductError::Canonical(
            CanonicalIntelligenceError::CanonicalRecallRunMismatch
        ))
    ));
}

#[test]
fn canonical_recall_uses_real_context_compiler_and_rejects_source_replacement() {
    let (mut ports, input, recall) = canonical_context();
    let receipt = ports
        .compile_context_with_canonical_recall(&input, &recall)
        .expect("actual context compilation");
    assert_eq!(receipt.stage, CanonicalStageV1::ContextCompiled);
    assert!(!receipt.output_digest.is_zero());
    assert!(!receipt.authority.grants_any());
    let (mut ports, input, recall) = canonical_context();
    ports.context_request.as_mut().expect("context").items[1].source_digest =
        digest("replaced event");
    assert!(
        ports
            .compile_context_with_canonical_recall(&input, &recall)
            .is_err()
    );
}

#[test]
fn canonical_recall_cannot_be_promoted_to_instruction_or_silently_omitted() {
    let (mut ports, input, recall) = canonical_context();
    ports.context_request.as_mut().expect("context").items[1].role =
        ContextRole::TrustedInstruction;
    assert!(
        ports
            .compile_context_with_canonical_recall(&input, &recall)
            .is_err()
    );
    let (mut ports, input, recall) = canonical_context();
    ports
        .context_request
        .as_mut()
        .expect("context")
        .token_budget = 2;
    assert!(
        ports
            .compile_context_with_canonical_recall(&input, &recall)
            .is_err()
    );
}

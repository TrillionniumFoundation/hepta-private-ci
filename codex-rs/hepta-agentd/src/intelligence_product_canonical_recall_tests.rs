use super::*;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf_learning::RecallAbstainReasonV1;
use codex_hepta_cognitive_types::hnmf_learning::RecallPacketV1;
use codex_hepta_cognitive_types::hnmf_learning::RecallResourceReceiptV1;
use codex_hepta_cognitive_types::hnmf_learning::SelectedEventRefV1;
use codex_hepta_intelligence::bind_canonical_recall_for_intelligence_v1;
use codex_hepta_memory_retrieval::CanonicalRecallSelectionBindingV1;
use codex_hepta_memory_retrieval::CanonicalRecallShadowContextV1;
use codex_hepta_memory_retrieval::RecallAbstentionReasonV1 as LegacyRecallAbstentionReasonV1;
use codex_hepta_memory_retrieval::RecallDispositionV1 as LegacyRecallDispositionV1;
use codex_hepta_memory_retrieval::RecallPacketV1 as LegacyRecallPacketV1;
use codex_hepta_memory_retrieval::RecallSelectionV1 as LegacyRecallSelectionV1;
use codex_hepta_memory_retrieval::RetrievalChannelV1;
use codex_hepta_memory_retrieval::adapt_generation_bound_recall_to_owned_canonical_v1;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;

pub(super) fn retrieval_owner_binding() -> OwnerBindingV1 {
    OwnerBindingV1 {
        owner_id: id("memory.retrieval"),
        generation: generation(8),
        implementation_digest: digest("memory.retrieval:impl"),
        key_digest: digest("memory.retrieval:key"),
        key_epoch: 8,
    }
}

fn owned_recall(run_id: StableId, packet: RecallPacketV1) -> AgentdCanonicalRecallInputV1 {
    let legacy_cue_digest = digest("legacy canonical recall cue");
    let legacy_candidate_union_digest = digest("legacy canonical recall union");
    let legacy_generation_vector_digest = digest("legacy canonical recall generation");
    let mut selection_bindings = Vec::with_capacity(packet.selected_events.len());
    let selections = packet
        .selected_events
        .iter()
        .map(|event| {
            let revision = Revision::new(event.revision).expect("legacy revision");
            selection_bindings.push(CanonicalRecallSelectionBindingV1 {
                legacy_record_id: id(event.event_id.as_str()),
                legacy_record_revision: revision,
                legacy_record_digest: event.event_digest.digest(),
                canonical_event: event.clone(),
            });
            LegacyRecallSelectionV1 {
                record_id: id(event.event_id.as_str()),
                record_revision: revision,
                record_digest: event.event_digest.digest(),
                weighted_score: FixedQ32::ONE,
                maximum_ood: ProbabilityQ32::ZERO,
                channels: vec![RetrievalChannelV1::Lexical],
                support_digests: vec![Digest32::of_parts(&[
                    b"agentd canonical recall test support\0",
                    event.event_digest.digest().as_array(),
                ])],
                contradiction_group_digests: Vec::new(),
            }
        })
        .collect::<Vec<_>>();
    let disposition = match packet.abstain {
        None => LegacyRecallDispositionV1::Recalled,
        Some(RecallAbstainReasonV1::NoCandidate) => {
            LegacyRecallDispositionV1::Abstained(LegacyRecallAbstentionReasonV1::NoCandidate)
        }
        Some(RecallAbstainReasonV1::OutOfDistribution) => {
            LegacyRecallDispositionV1::Abstained(LegacyRecallAbstentionReasonV1::OutOfDistribution)
        }
        Some(RecallAbstainReasonV1::LowConfidence) => {
            LegacyRecallDispositionV1::Abstained(LegacyRecallAbstentionReasonV1::ScoreBelowFloor)
        }
        Some(RecallAbstainReasonV1::UnresolvedContradiction) => {
            LegacyRecallDispositionV1::Abstained(
                LegacyRecallAbstentionReasonV1::ContradictoryEvidence,
            )
        }
        Some(RecallAbstainReasonV1::InsufficientCoverage) => LegacyRecallDispositionV1::Abstained(
            LegacyRecallAbstentionReasonV1::InsufficientChannelCoverage,
        ),
    };
    let mut legacy = LegacyRecallPacketV1 {
        cue_digest: legacy_cue_digest,
        policy_digest: digest("legacy canonical recall policy"),
        candidate_union_digest: legacy_candidate_union_digest,
        generation_vector_digest: legacy_generation_vector_digest,
        disposition,
        selections,
        omitted_count: 0,
        distinct_channels: if packet.abstain.is_none() { 1 } else { 0 },
        engram: None,
        packet_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    legacy.packet_digest = legacy.compute_packet_digest();
    legacy.validate().expect("legacy retrieval packet");
    let operation_id = ContractIdV1::new(run_id.to_string()).expect("operation id");
    let owned = adapt_generation_bound_recall_to_owned_canonical_v1(
        operation_id,
        &legacy,
        CanonicalRecallShadowContextV1 {
            legacy_cue_digest,
            legacy_candidate_union_digest,
            legacy_generation_vector_digest,
            canonical_cue_digest: packet.cue_digest,
            selection_bindings,
            event_snapshot_digest: packet.event_snapshot_digest,
            engram_snapshot_digest: packet.engram_snapshot_digest,
            active_nodes: packet.active_nodes.clone(),
            activation_paths: packet.activation_paths.clone(),
            contradictions: packet.contradictions.clone(),
            coverage_ppm: packet.coverage_ppm,
            confidence_ppm: packet.confidence_ppm,
            ood_ppm: packet.ood_ppm,
            resource_receipt: packet.resource_receipt,
        },
    )
    .expect("retrieval-owned canonical recall");
    bind_retrieval_owned_canonical_recall_for_agentd_v1(run_id, owned, retrieval_owner_binding())
        .expect("Agentd retrieval binding")
}

pub(super) fn explicit_absence_recall(run_id: StableId) -> AgentdCanonicalRecallInputV1 {
    let packet = RecallPacketV1 {
        cue_digest: ContractDigestV1::from_digest(digest("explicit absence cue"))
            .expect("cue digest"),
        event_snapshot_digest: ContractDigestV1::from_digest(digest("explicit absence memory cut"))
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
    owned_recall(run_id, packet)
}

fn canonical_context() -> (
    AgentdOwnerPortsV1,
    CanonicalPortInputV1,
    CanonicalRecallPortInputV1,
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
    assert_eq!(
        recall.retrieval_owner().owner_id.as_str(),
        "memory.retrieval"
    );
}

#[test]
fn wrong_retrieval_owner_cannot_be_substituted() {
    let packet = explicit_absence_recall(id("run:owner-substitution"));
    let mut wrong = packet.retrieval_owner().clone();
    wrong.owner_id = id("context.compiler");
    assert!(
        bind_retrieval_owned_canonical_recall_for_agentd_v1(
            id("run:owner-substitution"),
            packet.retrieval().clone(),
            wrong,
        )
        .is_err()
    );
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
            message.contains("requires an explicit retrieval-owned canonical recall result"),
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

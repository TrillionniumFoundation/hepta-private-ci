//! Semantic regression tests and deterministic policy-grid properties.
//! These exercise the Rust implementation, not a separately reimplemented model.

use crate::*;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("test id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn cue() -> MemoryCueV1 {
    MemoryCueV1 {
        cue_id: id("cue:semantics"),
        objective_digest: digest("objective"),
        approved_context_digest: digest("approved-context"),
        request_digest: digest("request"),
        snapshot_key: CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
            scope_id: id("scope:semantics"),
            purpose_id: id("purpose:recall"),
            memory_ledger_frontier: 10,
            knowledge_fact_frontier: 8,
            tombstone_frontier: 4,
            source_ledger_frontier: 11,
            knowledge_graph_generation: Generation::new(2).expect("generation"),
            compact_checkpoint_generation: Generation::new(1).expect("generation"),
            prompt_registry_revision: Revision::new(3).expect("revision"),
            retrieval_profile_digest: digest("retrieval-profile"),
            encoder_preprocessor_digest: digest("encoder-profile"),
            authority_epoch: 5,
            model_digest: digest("model"),
            tokenizer_digest: digest("tokenizer"),
            template_digest: digest("template"),
            tool_schema_digest: digest("tool-schema"),
        })
        .expect("snapshot"),
        cue_profile_digest: digest("cue-profile"),
    }
}

fn policy() -> RetrievalPolicyV1 {
    RetrievalPolicyV1 {
        policy_id: id("policy:semantics"),
        channel_weights: vec![RetrievalChannelWeightV1 {
            channel: RetrievalChannelV1::Lexical,
            weight: FixedQ32::ONE,
            maximum_candidates: 512,
        }],
        maximum_results: 16,
        minimum_total_score: FixedQ32::ZERO,
        maximum_ood: ProbabilityQ32::ONE,
        minimum_distinct_channels: 1,
        abstain_on_contradiction: true,
    }
}

fn dynamics() -> EngramDynamicsPolicyV1 {
    let mut result = EngramDynamicsPolicyV1::product_default().expect("dynamics");
    result.leak = FixedQ32::ZERO;
    result.lateral_inhibition = FixedQ32::ZERO;
    result.minimum_activation = FixedQ32::ZERO;
    result
}

fn candidate(number: u32, score: i64) -> RetrievalChannelCandidateV1 {
    RetrievalChannelCandidateV1 {
        record: MemoryRecord {
            record_id: id(&format!("memory:{number:04}")),
            revision: Revision::new(1).expect("revision"),
            kind: MemoryKind::Fact,
            content_digest: digest(&format!("content:{number}")),
            predecessor_digest: None,
            citations: Vec::new(),
            state: RecordState::Live,
        },
        channel: RetrievalChannelV1::Lexical,
        channel_rank: number,
        normalized_score: FixedQ32::from_raw(score),
        ood: ProbabilityQ32::ZERO,
        support_digest: digest(&format!("support:{number}")),
        contradiction_group_digest: None,
        generation_vector_digest: cue().snapshot_key.vector_digest,
    }
}

fn snapshot(candidates: &[RetrievalChannelCandidateV1]) -> EngramSnapshotV1 {
    let nodes = candidates
        .iter()
        .map(|candidate| EngramNodeV1 {
            node_id: candidate.record.record_id.clone(),
            population: EngramPopulationV1::SemanticConcept,
            support: vec![EngramSupportV1 {
                record_id: candidate.record.record_id.clone(),
                record_revision: candidate.record.revision,
            }],
            threshold: FixedQ32::ZERO,
            confidence: ProbabilityQ32::ONE,
            generation_vector_digest: cue().snapshot_key.vector_digest,
        })
        .collect();
    EngramSnapshotV1::new(
        cue().snapshot_key.vector_digest,
        digest("engram-generation"),
        nodes,
        Vec::new(),
    )
    .expect("snapshot")
}

fn claim(proposition: &str, polarity: PropositionPolarityV2) -> ContradictionEvidenceV2 {
    ContradictionEvidenceV2::new(
        digest(proposition),
        cue().snapshot_key.vector_digest,
        polarity,
    )
    .expect("claim")
}

fn both(
    policy: &RetrievalPolicyV1,
    candidates: Vec<RetrievalChannelCandidateV1>,
) -> [RecallPacketV1; 2] {
    let graph = snapshot(&candidates);
    [
        recall(&cue(), policy, candidates.clone()).expect("plain recall"),
        recall_with_engram(&cue(), policy, candidates, &graph, &dynamics()).expect("engram recall"),
    ]
}

#[test]
fn multiple_same_side_contradiction_supports_never_imply_opposite_polarity() {
    for polarity in [
        PropositionPolarityV2::Affirmed,
        PropositionPolarityV2::Denied,
        PropositionPolarityV2::ConflictReported,
    ] {
        let mut policy = policy();
        policy.channel_weights[0].channel = RetrievalChannelV1::ContradictionSupport;
        let candidates = (1..=4)
            .map(|number| {
                let mut value = candidate(number, FixedQ32::ONE.raw());
                value.channel = RetrievalChannelV1::ContradictionSupport;
                value.contradiction_group_digest = Some(claim("same-proposition", polarity));
                value
            })
            .collect();
        for packet in both(&policy, candidates) {
            assert_eq!(packet.disposition, RecallDispositionV1::Recalled);
            assert_eq!(packet.selections.len(), 4);
        }
    }
}

#[test]
fn opposite_polarities_require_the_same_proposition() {
    let mut positive = candidate(1, FixedQ32::ONE.raw());
    positive.contradiction_group_digest = Some(claim("p", PropositionPolarityV2::Affirmed));
    let mut negative = candidate(2, FixedQ32::ONE.raw());
    negative.contradiction_group_digest = Some(claim("q", PropositionPolarityV2::Denied));
    for packet in both(&policy(), vec![positive.clone(), negative.clone()]) {
        assert_eq!(packet.disposition, RecallDispositionV1::Recalled);
    }
    negative.contradiction_group_digest = Some(claim("p", PropositionPolarityV2::Denied));
    for packet in both(&policy(), vec![positive, negative]) {
        assert_eq!(
            packet.disposition,
            RecallDispositionV1::Abstained(RecallAbstentionReasonV1::ContradictoryEvidence)
        );
        assert!(packet.selections.is_empty());
    }
}

#[test]
fn claim_generation_is_checked_even_when_candidate_generation_matches() {
    let mut value = candidate(1, FixedQ32::ONE.raw());
    let mut evidence = claim("p", PropositionPolarityV2::Affirmed);
    evidence.generation_vector_digest = digest("other-generation");
    value.contradiction_group_digest = Some(evidence);
    assert!(matches!(
        recall(&cue(), &policy(), vec![value.clone()]),
        Err(RecallErrorV1::GenerationVectorMismatch(_))
    ));
    let batch = RetrievalGeneratorBatchV1 {
        receipt: RetrievalGeneratorReceiptV1::new(
            RetrievalGeneratorOwnerV1::CognitiveLexical,
            cue().snapshot_key.vector_digest,
            digest("owner-generation"),
            1,
            RetrievalSourceCompletenessV1::Exhausted,
        )
        .expect("receipt"),
        candidates: vec![value],
    };
    assert!(matches!(batch.validate(), Err(GeneratorErrorV1::Recall(_))));
}

#[test]
fn below_floor_ood_and_opposite_claim_do_not_poison_admitted_recall() {
    let mut policy = policy();
    policy.minimum_total_score = FixedQ32::from_raw(1_i64 << 31);
    policy.maximum_ood = ProbabilityQ32::ZERO;
    let mut high = candidate(1, FixedQ32::ONE.raw());
    high.contradiction_group_digest = Some(claim("p", PropositionPolarityV2::Affirmed));
    let mut low = candidate(2, 1_i64 << 30);
    low.ood = ProbabilityQ32::ONE;
    low.contradiction_group_digest = Some(claim("p", PropositionPolarityV2::Denied));
    let baseline = both(&policy, vec![high.clone()]);
    for (before, after) in baseline.into_iter().zip(both(&policy, vec![high, low])) {
        assert_eq!(after.disposition, RecallDispositionV1::Recalled);
        assert_eq!(after.selections, before.selections);
        assert_eq!(after.omitted_count, 1);
        if let Some(engram) = after.engram {
            assert_eq!(engram.resources.candidate_records, 2);
            assert_eq!(engram.selected_support.len(), 1);
            assert_eq!(engram.coverage.raw(), ProbabilityQ32::ONE.raw() / 2);
        }
    }
}

#[test]
fn admitted_high_ood_still_abstains() {
    let mut policy = policy();
    policy.maximum_ood = ProbabilityQ32::ZERO;
    let mut value = candidate(1, FixedQ32::ONE.raw());
    value.ood = ProbabilityQ32::ONE;
    for packet in both(&policy, vec![value]) {
        assert_eq!(
            packet.disposition,
            RecallDispositionV1::Abstained(RecallAbstentionReasonV1::OutOfDistribution)
        );
    }
}

#[test]
fn zero_minimum_activation_does_not_activate_thresholded_nodes() {
    let candidates = vec![candidate(1, FixedQ32::ONE.raw())];
    let mut graph = snapshot(&candidates);
    graph.nodes[0].threshold = FixedQ32::ONE;
    graph.snapshot_digest = graph.compute_snapshot_digest();
    let union = build_candidate_union(&cue(), &policy(), candidates).expect("union");
    let receipt = settle_engram(&cue(), &union, &graph, &dynamics()).expect("receipt");
    assert!(receipt.active_nodes.is_empty());
    assert!(receipt.selected_support.is_empty());
    assert_eq!(receipt.resources.active_nodes, 0);
    assert_eq!(receipt.coverage, ProbabilityQ32::ZERO);
    assert_eq!(receipt.confidence, ProbabilityQ32::ZERO);
}

#[test]
fn zero_active_node_is_rejected_after_receipt_rehash() {
    let candidates = vec![candidate(1, FixedQ32::ONE.raw())];
    let graph = snapshot(&candidates);
    let union = build_candidate_union(&cue(), &policy(), candidates).expect("union");
    let mut receipt = settle_engram(&cue(), &union, &graph, &dynamics()).expect("receipt");
    receipt.active_nodes[0].activation = FixedQ32::ZERO;
    receipt.receipt_digest = receipt.compute_receipt_digest();
    assert_eq!(
        receipt.validate(),
        Err(EngramErrorV1::ScoreOutOfRange("active_node_activation"))
    );
}

#[test]
fn zero_contribution_cannot_supply_channel_coverage() {
    let mut policy = policy();
    policy.channel_weights.push(RetrievalChannelWeightV1 {
        channel: RetrievalChannelV1::Entity,
        weight: FixedQ32::ONE,
        maximum_candidates: 512,
    });
    policy.minimum_distinct_channels = 2;
    let high = candidate(1, FixedQ32::ONE.raw());
    let mut zero = candidate(2, 0);
    zero.channel = RetrievalChannelV1::Entity;
    zero.ood = ProbabilityQ32::ONE;
    for packet in both(&policy, vec![high, zero]) {
        assert_eq!(
            packet.disposition,
            RecallDispositionV1::Abstained(RecallAbstentionReasonV1::InsufficientChannelCoverage)
        );
        assert_eq!(packet.distinct_channels, 1);
    }
}

#[test]
fn every_zero_weight_synapse_is_inert_including_expansion_and_conflicts() {
    let candidates = vec![
        candidate(1, FixedQ32::ONE.raw()),
        candidate(2, FixedQ32::ONE.raw()),
    ];
    let mut graph = snapshot(&[
        candidates[0].clone(),
        candidates[1].clone(),
        candidate(3, 1),
    ]);
    let baseline = recall_with_engram(&cue(), &policy(), candidates.clone(), &graph, &dynamics())
        .expect("baseline");
    for relation in [
        SynapseRelationV1::Associative,
        SynapseRelationV1::Temporal,
        SynapseRelationV1::Causal,
        SynapseRelationV1::Procedural,
        SynapseRelationV1::Predictive,
        SynapseRelationV1::Supports,
        SynapseRelationV1::Inhibitory,
        SynapseRelationV1::Contradicts,
    ] {
        graph.synapses = [2, 3]
            .into_iter()
            .map(|target| SynapseV1 {
                source_node_id: id("memory:0001"),
                target_node_id: id(&format!("memory:{target:04}")),
                relation,
                weight: FixedQ32::ZERO,
                support_digest: digest("edge-support"),
                generation_vector_digest: cue().snapshot_key.vector_digest,
            })
            .collect();
        graph.snapshot_digest = graph.compute_snapshot_digest();
        let packet = recall_with_engram(&cue(), &policy(), candidates.clone(), &graph, &dynamics())
            .expect("zero edge recall");
        assert_eq!(packet.disposition, baseline.disposition);
        assert_eq!(packet.selections, baseline.selections);
        let actual = packet.engram.expect("engram");
        let expected = baseline.engram.as_ref().expect("engram");
        assert_eq!(actual.active_nodes, expected.active_nodes);
        assert_eq!(actual.resources, expected.resources);
        assert!(actual.contradictions.is_empty());
        assert_eq!(actual.resources.expanded_nodes, 2);
    }
}

#[test]
fn confidence_is_activation_weighted_not_node_count_weighted() {
    let candidates = vec![candidate(1, 3_i64 << 30), candidate(2, 1_i64 << 30)];
    let mut graph = snapshot(&candidates);
    graph.nodes[1].confidence = ProbabilityQ32::ZERO;
    graph.snapshot_digest = graph.compute_snapshot_digest();
    let packet =
        recall_with_engram(&cue(), &policy(), candidates, &graph, &dynamics()).expect("recall");
    assert_eq!(
        packet.engram.expect("engram").confidence.raw(),
        3 * ProbabilityQ32::ONE.raw() / 4
    );
}

#[test]
fn policy_grid_preserves_permutation_and_resource_accounting() {
    for weight in [1_i64, 1_i64 << 30, FixedQ32::ONE.raw()] {
        for floor in [0_i64, 1_i64, 1_i64 << 31, FixedQ32::ONE.raw()] {
            for maximum_results in [1, 4, 16] {
                for count in [1_u32, 2, 17, 64] {
                    let mut policy = policy();
                    policy.channel_weights[0].weight = FixedQ32::from_raw(weight);
                    policy.minimum_total_score = FixedQ32::from_raw(floor);
                    policy.maximum_results = maximum_results;
                    policy.validate().expect("grid policy");
                    let candidates = (1..=count)
                        .map(|number| candidate(number, FixedQ32::ONE.raw() / i64::from(number)))
                        .collect::<Vec<_>>();
                    let union =
                        build_candidate_union(&cue(), &policy, candidates.clone()).expect("union");
                    let mut reversed = candidates.clone();
                    reversed.reverse();
                    assert_eq!(
                        union,
                        build_candidate_union(&cue(), &policy, reversed.clone())
                            .expect("reversed union")
                    );
                    for (left, right) in both(&policy, candidates)
                        .into_iter()
                        .zip(both(&policy, reversed))
                    {
                        assert_eq!(left, right);
                        left.validate().expect("packet invariants");
                        assert!(left.selections.len() <= maximum_results as usize);
                        if left.disposition == RecallDispositionV1::Recalled {
                            assert_eq!(
                                left.selections.len() + left.omitted_count as usize,
                                union.entries.len()
                            );
                        }
                        if let Some(receipt) = left.engram {
                            assert_eq!(
                                receipt.resources.candidate_records as usize,
                                union.entries.len()
                            );
                            assert_eq!(
                                receipt.resources.active_nodes as usize,
                                receipt.active_nodes.len()
                            );
                            assert!(
                                receipt
                                    .active_nodes
                                    .iter()
                                    .all(|node| node.activation > FixedQ32::ZERO)
                            );
                        }
                    }
                }
            }
        }
    }
}

#[test]
fn candidate_ceiling_is_fail_closed_before_semantic_filtering() {
    let values = (1..=513).map(|number| candidate(number, 0)).collect();
    assert_eq!(
        build_candidate_union(&cue(), &policy(), values),
        Err(RecallErrorV1::CandidateLimitExceeded)
    );
}

#[test]
fn policy_row_order_does_not_change_receipts() {
    let mut policy = policy();
    policy.channel_weights.push(RetrievalChannelWeightV1 {
        channel: RetrievalChannelV1::Entity,
        weight: FixedQ32::ONE,
        maximum_candidates: 512,
    });
    let first = candidate(1, FixedQ32::ONE.raw());
    let mut second = candidate(2, FixedQ32::ONE.raw());
    second.channel = RetrievalChannelV1::Entity;
    let candidates = vec![first, second];
    let expected = both(&policy, candidates.clone());
    policy.channel_weights.reverse();
    assert_eq!(expected, both(&policy, candidates));
}

#[test]
fn another_cue_at_the_same_generation_cannot_reuse_an_engram_union() {
    let candidates = vec![candidate(1, FixedQ32::ONE.raw())];
    let graph = snapshot(&candidates);
    let union = build_candidate_union(&cue(), &policy(), candidates).expect("union");
    let mut other = cue();
    other.request_digest = digest("different-request");
    assert!(matches!(
        settle_engram(&other, &union, &graph, &dynamics()),
        Err(EngramErrorV1::Recall(RecallErrorV1::DigestMismatch(
            "engram_cue"
        )))
    ));
}

#[test]
fn controlled_recall_preserves_complete_results_and_never_returns_partial_success() {
    use std::time::Duration;
    use std::time::Instant;

    let candidates = vec![
        candidate(1, FixedQ32::ONE.raw()),
        candidate(2, FixedQ32::ONE.raw() / 2),
    ];
    let graph = snapshot(&candidates);
    let expected =
        recall_with_engram(&cue(), &policy(), candidates.clone(), &graph, &dynamics()).unwrap();
    let work = RecallWorkControlV1::bounded(Instant::now() + Duration::from_secs(30), 10000);
    let actual = recall_with_engram_controlled(
        &cue(),
        &policy(),
        candidates.clone(),
        &graph,
        &dynamics(),
        &work,
    )
    .unwrap();
    assert_eq!(actual, expected);
    work.cancel();
    assert_eq!(
        recall_with_engram_controlled(&cue(), &policy(), candidates, &graph, &dynamics(), &work),
        Err(EngramErrorV1::Recall(RecallErrorV1::Interrupted(
            RecallInterruptionV1::Cancelled
        ))),
    );
}

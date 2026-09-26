use super::*;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf_learning::RecallAbstainReasonV1 as CanonicalRecallAbstainReasonV1;
use codex_hepta_cognitive_types::hnmf_learning::RecallResourceReceiptV1 as CanonicalRecallResourceReceiptV1;
use codex_hepta_cognitive_types::hnmf_learning::SelectedEventRefV1 as CanonicalSelectedEventRefV1;

use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::Generation;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn revision(value: u64) -> Revision {
    Revision::new(value).unwrap_or_else(|error| panic!("valid revision: {error}"))
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("valid generation: {error}"))
}

fn probability(raw: u64) -> ProbabilityQ32 {
    ProbabilityQ32::from_raw(raw).unwrap_or_else(|error| panic!("valid probability: {error}"))
}

fn snapshot_key() -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:retrieval"),
        purpose_id: id("purpose:recall"),
        memory_ledger_frontier: 10,
        knowledge_fact_frontier: 8,
        tombstone_frontier: 4,
        source_ledger_frontier: 11,
        knowledge_graph_generation: generation(2),
        compact_checkpoint_generation: generation(1),
        prompt_registry_revision: revision(3),
        retrieval_profile_digest: digest("retrieval-profile"),
        encoder_preprocessor_digest: digest("encoder-profile"),
        authority_epoch: 5,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
    })
    .unwrap_or_else(|error| panic!("valid snapshot key: {error}"))
}

fn cue() -> MemoryCueV1 {
    MemoryCueV1 {
        cue_id: id("cue:1"),
        objective_digest: digest("objective"),
        approved_context_digest: digest("approved-context"),
        request_digest: digest("request"),
        snapshot_key: snapshot_key(),
        cue_profile_digest: digest("cue-profile"),
    }
}

fn policy() -> RetrievalPolicyV1 {
    RetrievalPolicyV1 {
        policy_id: id("policy:1"),
        channel_weights: vec![
            RetrievalChannelWeightV1 {
                channel: RetrievalChannelV1::Lexical,
                weight: FixedQ32::from_raw(1_i64 << 31),
                maximum_candidates: 16,
            },
            RetrievalChannelWeightV1 {
                channel: RetrievalChannelV1::Entity,
                weight: FixedQ32::from_raw(1_i64 << 31),
                maximum_candidates: 16,
            },
            RetrievalChannelWeightV1 {
                channel: RetrievalChannelV1::ContradictionSupport,
                weight: FixedQ32::from_raw(1_i64 << 30),
                maximum_candidates: 16,
            },
        ],
        maximum_results: 8,
        minimum_total_score: FixedQ32::from_raw(1_i64 << 30),
        maximum_ood: probability(1_u64 << 30),
        minimum_distinct_channels: 2,
        abstain_on_contradiction: true,
    }
}

fn record(number: u64) -> MemoryRecord {
    MemoryRecord {
        record_id: id(&format!("memory:{number}")),
        revision: revision(1),
        kind: MemoryKind::Fact,
        content_digest: digest(&format!("content-{number}")),
        predecessor_digest: None,
        citations: vec![Citation {
            source_id: id(&format!("source:{number}")),
            source_digest: digest(&format!("source-{number}")),
        }],
        state: RecordState::Live,
    }
}

fn candidate(
    record: MemoryRecord,
    channel: RetrievalChannelV1,
    rank: u32,
) -> RetrievalChannelCandidateV1 {
    RetrievalChannelCandidateV1 {
        generation_vector_digest: cue().snapshot_key.vector_digest,
        support_digest: digest(&format!("support-{}-{channel:?}", record.record_id)),
        contradiction_evidence: None,
        normalized_score: FixedQ32::ONE,
        ood: probability(1_u64 << 28),
        record,
        channel,
        channel_rank: rank,
    }
}

#[test]
fn channel_completion_order_cannot_change_union_or_recall() {
    let cue = cue();
    let policy = policy();
    let first = record(1);
    let second = record(2);
    let candidates = vec![
        candidate(first.clone(), RetrievalChannelV1::Lexical, 1),
        candidate(first, RetrievalChannelV1::Entity, 1),
        candidate(second.clone(), RetrievalChannelV1::Lexical, 2),
        candidate(second, RetrievalChannelV1::Entity, 2),
    ];
    let mut reversed = candidates.clone();
    reversed.reverse();

    let left = build_candidate_union(&cue, &policy, candidates.clone())
        .unwrap_or_else(|error| panic!("valid union: {error}"));
    let right = build_candidate_union(&cue, &policy, reversed.clone())
        .unwrap_or_else(|error| panic!("valid union: {error}"));
    assert_eq!(left, right);

    let left =
        recall(&cue, &policy, candidates).unwrap_or_else(|error| panic!("valid recall: {error}"));
    let right =
        recall(&cue, &policy, reversed).unwrap_or_else(|error| panic!("valid recall: {error}"));
    assert_eq!(left, right);
    assert_eq!(left.disposition, RecallDispositionV1::Recalled);
    assert_eq!(left.selections.len(), 2);
}

#[test]
fn high_risk_contradiction_forces_abstention() {
    let cue = cue();
    let policy = policy();
    let proposition = digest("contradiction-proposition");
    let mut first = candidate(record(1), RetrievalChannelV1::Lexical, 1);
    first.contradiction_evidence = Some(ContradictionEvidenceV1 {
        proposition_digest: proposition,
        polarity: ContradictionPolarityV1::Supports,
    });
    let mut second = candidate(record(2), RetrievalChannelV1::Entity, 1);
    second.contradiction_evidence = Some(ContradictionEvidenceV1 {
        proposition_digest: proposition,
        polarity: ContradictionPolarityV1::Opposes,
    });
    let packet = recall(&cue, &policy, vec![first, second])
        .unwrap_or_else(|error| panic!("valid abstention: {error}"));
    assert_eq!(
        packet.disposition,
        RecallDispositionV1::Abstained(RecallAbstentionReasonV1::ContradictoryEvidence)
    );
    assert!(packet.selections.is_empty());
}

#[test]
fn multiple_same_polarity_contradiction_supports_do_not_abstain() {
    let cue = cue();
    let policy = policy();
    let proposition = digest("same-side-proposition");
    let evidence = ContradictionEvidenceV1 {
        proposition_digest: proposition,
        polarity: ContradictionPolarityV1::Opposes,
    };
    let mut first = candidate(record(1), RetrievalChannelV1::Lexical, 1);
    first.contradiction_evidence = Some(evidence);
    let mut second = candidate(record(2), RetrievalChannelV1::Entity, 1);
    second.contradiction_evidence = Some(evidence);
    let packet = recall(&cue, &policy, vec![first, second])
        .unwrap_or_else(|error| panic!("same-side evidence is valid: {error}"));
    assert_eq!(packet.disposition, RecallDispositionV1::Recalled);
    assert_eq!(packet.selections.len(), 2);
}

#[test]
fn stale_generation_candidate_is_rejected_before_ranking() {
    let cue = cue();
    let policy = policy();
    let mut stale = candidate(record(1), RetrievalChannelV1::Lexical, 1);
    stale.generation_vector_digest = digest("stale-vector");
    assert_eq!(
        recall(&cue, &policy, vec![stale]),
        Err(RecallErrorV1::GenerationVectorMismatch(
            "memory:1".to_string()
        ))
    );
}

#[test]
fn ood_and_insufficient_coverage_abstain_explicitly() {
    let cue = cue();
    let policy = policy();
    let only_one_channel = candidate(record(1), RetrievalChannelV1::Lexical, 1);
    let packet = recall(&cue, &policy, vec![only_one_channel])
        .unwrap_or_else(|error| panic!("coverage abstention: {error}"));
    assert_eq!(
        packet.disposition,
        RecallDispositionV1::Abstained(RecallAbstentionReasonV1::InsufficientChannelCoverage)
    );

    let mut ood_policy = policy();
    ood_policy.minimum_distinct_channels = 1;
    ood_policy.channel_weights = vec![RetrievalChannelWeightV1 {
        channel: RetrievalChannelV1::Lexical,
        weight: FixedQ32::ONE,
        maximum_candidates: 16,
    }];
    let mut out_of_distribution = candidate(record(2), RetrievalChannelV1::Lexical, 1);
    out_of_distribution.ood = ProbabilityQ32::ONE;
    let packet = recall(&cue, &ood_policy, vec![out_of_distribution])
        .unwrap_or_else(|error| panic!("ood abstention: {error}"));
    assert_eq!(
        packet.disposition,
        RecallDispositionV1::Abstained(RecallAbstentionReasonV1::OutOfDistribution)
    );
}

#[test]
fn tombstones_and_duplicate_channel_candidates_fail_closed() {
    let cue = cue();
    let policy = policy();
    let mut deleted = record(1);
    deleted.state = RecordState::Tombstone;
    assert_eq!(
        recall(
            &cue,
            &policy,
            vec![candidate(deleted, RetrievalChannelV1::Lexical, 1)]
        ),
        Err(RecallErrorV1::TombstoneCandidate("memory:1".to_string()))
    );

    let duplicate = candidate(record(2), RetrievalChannelV1::Lexical, 1);
    assert_eq!(
        recall(&cue, &policy, vec![duplicate.clone(), duplicate]),
        Err(RecallErrorV1::DuplicateChannelCandidate(
            "memory:2".to_string()
        ))
    );
}

#[test]
fn zero_weight_channel_cannot_satisfy_coverage() {
    let _cue = cue();
    let mut policy = policy();
    policy.channel_weights = vec![
        RetrievalChannelWeightV1 {
            channel: RetrievalChannelV1::Lexical,
            weight: FixedQ32::ONE,
            maximum_candidates: 16,
        },
        RetrievalChannelWeightV1 {
            channel: RetrievalChannelV1::Entity,
            weight: FixedQ32::ZERO,
            maximum_candidates: 16,
        },
    ];
    policy.minimum_distinct_channels = 2;
    assert_eq!(
        policy.validate(),
        Err(RecallErrorV1::InvalidMinimumCoverage)
    );
}

#[test]
fn score_floor_applies_to_every_returned_selection() {
    let cue = cue();
    let mut policy = policy();
    policy.minimum_total_score = FixedQ32::from_raw(1_i64 << 31);
    policy.minimum_distinct_channels = 1;
    policy.channel_weights = vec![RetrievalChannelWeightV1 {
        channel: RetrievalChannelV1::Lexical,
        weight: FixedQ32::ONE,
        maximum_candidates: 16,
    }];
    let high = candidate(record(1), RetrievalChannelV1::Lexical, 1);
    let mut low = candidate(record(2), RetrievalChannelV1::Lexical, 2);
    low.normalized_score = FixedQ32::from_raw(1);
    let packet = recall(&cue, &policy, vec![high, low])
        .unwrap_or_else(|error| panic!("valid recall: {error}"));
    assert_eq!(packet.disposition, RecallDispositionV1::Recalled);
    assert_eq!(packet.selections.len(), 1);
    assert_eq!(packet.selections[0].record_id, id("memory:1"));
    assert_eq!(packet.omitted_count, 1);
}

#[test]
fn low_score_or_high_ood_candidate_cannot_poison_admitted_recall() {
    let cue = cue();
    let mut policy = policy();
    policy.minimum_distinct_channels = 1;
    policy.minimum_total_score = FixedQ32::from_raw(1_i64 << 31);
    policy.channel_weights = vec![
        RetrievalChannelWeightV1 {
            channel: RetrievalChannelV1::Lexical,
            weight: FixedQ32::ONE,
            maximum_candidates: 16,
        },
        RetrievalChannelWeightV1 {
            channel: RetrievalChannelV1::ContradictionSupport,
            weight: FixedQ32::ONE,
            maximum_candidates: 16,
        },
    ];
    let high = candidate(record(1), RetrievalChannelV1::Lexical, 1);
    let baseline = recall(&cue, &policy, vec![high.clone()]).expect("baseline");

    let mut poison = candidate(record(2), RetrievalChannelV1::ContradictionSupport, 1);
    poison.normalized_score = FixedQ32::from_raw(1);
    poison.ood = ProbabilityQ32::ONE;
    poison.contradiction_evidence = Some(ContradictionEvidenceV1 {
        proposition_digest: digest("unadmitted-poison"),
        polarity: ContradictionPolarityV1::Opposes,
    });
    let with_poison = recall(&cue, &policy, vec![high, poison]).expect("poison excluded");
    assert_eq!(baseline.disposition, RecallDispositionV1::Recalled);
    assert_eq!(with_poison.disposition, RecallDispositionV1::Recalled);
    assert_eq!(baseline.selections[0].record_id, with_poison.selections[0].record_id);
    assert_eq!(with_poison.omitted_count, 1);
}

#[test]
fn public_union_and_packet_validators_reject_structural_tampering() {
    let cue = cue();
    let policy = policy();
    let first = record(1);
    let second = record(2);
    let candidates = vec![
        candidate(first.clone(), RetrievalChannelV1::Lexical, 1),
        candidate(first, RetrievalChannelV1::Entity, 1),
        candidate(second.clone(), RetrievalChannelV1::Lexical, 2),
        candidate(second, RetrievalChannelV1::Entity, 2),
    ];
    let union = build_candidate_union(&cue, &policy, candidates.clone())
        .unwrap_or_else(|error| panic!("union: {error}"));
    let mut reordered = union;
    reordered.entries.reverse();
    reordered.union_digest = reordered.compute_union_digest();
    assert_eq!(
        reordered.validate(),
        Err(RecallErrorV1::NonCanonicalCollection("union_entries"))
    );

    let packet =
        recall(&cue, &policy, candidates).unwrap_or_else(|error| panic!("recall: {error}"));
    let mut duplicate = packet;
    duplicate.selections.push(duplicate.selections[0].clone());
    duplicate.packet_digest = duplicate.compute_packet_digest();
    assert_eq!(
        duplicate.validate(),
        Err(RecallErrorV1::DuplicateRecallSelection(
            duplicate.selections[0].record_id.to_string()
        ))
    );
}

#[test]
fn public_packet_validator_rejects_impossible_counts_after_rehash() {
    let cue = cue();
    let mut policy = policy();
    policy.minimum_distinct_channels = 1;
    let candidates = vec![
        candidate(record(1), RetrievalChannelV1::Lexical, 1),
        candidate(record(2), RetrievalChannelV1::Entity, 1),
    ];
    let packet =
        recall(&cue, &policy, candidates).unwrap_or_else(|error| panic!("recall: {error}"));

    let mut impossible_omission = packet.clone();
    impossible_omission.omitted_count =
        u32::try_from(MAX_GENERATION_BOUND_CANDIDATES).expect("bound");
    impossible_omission.packet_digest = impossible_omission.compute_packet_digest();
    assert_eq!(
        impossible_omission.validate(),
        Err(RecallErrorV1::CandidateLimitExceeded)
    );

    let mut impossible_channels = packet;
    impossible_channels.distinct_channels = RETRIEVAL_CHANNEL_COUNT + 1;
    impossible_channels.packet_digest = impossible_channels.compute_packet_digest();
    assert_eq!(
        impossible_channels.validate(),
        Err(RecallErrorV1::InvalidRecallChannelCount)
    );
}

#[test]
fn property_all_candidate_permutations_have_one_union_and_recall() {
    let cue = cue();
    let mut policy = policy();
    policy.minimum_distinct_channels = 1;
    let candidates = [
        candidate(record(1), RetrievalChannelV1::Lexical, 1),
        candidate(record(2), RetrievalChannelV1::Entity, 1),
        candidate(record(3), RetrievalChannelV1::ContradictionSupport, 1),
    ];
    let mut order = vec![0_usize, 1, 2];
    let mut expected_union = None;
    let mut expected_recall = None;
    loop {
        let permutation = order
            .iter()
            .map(|index| candidates[*index].clone())
            .collect::<Vec<_>>();
        let union = build_candidate_union(&cue, &policy, permutation.clone())
            .unwrap_or_else(|error| panic!("union: {error}"));
        let recall =
            recall(&cue, &policy, permutation).unwrap_or_else(|error| panic!("recall: {error}"));
        if let Some(expected) = &expected_union {
            assert_eq!(expected, &union);
        } else {
            expected_union = Some(union);
        }
        if let Some(expected) = &expected_recall {
            assert_eq!(expected, &recall);
        } else {
            expected_recall = Some(recall);
        }
        if !next_permutation(&mut order) {
            break;
        }
    }
}

#[test]
fn property_legal_policy_matrix_is_order_invariant_and_bounded() {
    let cue = cue();
    for maximum_results in 1..=4 {
        for minimum_score in [0_i64, 1, 1_i64 << 30, 1_i64 << 31] {
            for maximum_ood in [1_u64 << 28, 1_u64 << 31, ProbabilityQ32::ONE.raw()] {
                let mut policy = policy();
                policy.maximum_results = maximum_results;
                policy.minimum_distinct_channels = 1;
                policy.minimum_total_score = FixedQ32::from_raw(minimum_score);
                policy.maximum_ood = probability(maximum_ood);
                let candidates = [
                    candidate(record(1), RetrievalChannelV1::Lexical, 1),
                    candidate(record(2), RetrievalChannelV1::Entity, 1),
                    candidate(record(3), RetrievalChannelV1::ContradictionSupport, 1),
                ];
                let mut order = vec![0_usize, 1, 2];
                let mut expected = None;
                loop {
                    let permutation = order
                        .iter()
                        .map(|index| candidates[*index].clone())
                        .collect::<Vec<_>>();
                    let packet = recall(&cue, &policy, permutation).expect("legal policy");
                    assert!(packet.selections.len() <= usize::try_from(maximum_results).unwrap());
                    assert!(
                        packet.selections.len()
                            + usize::try_from(packet.omitted_count).unwrap_or(usize::MAX)
                            <= candidates.len()
                    );
                    if let Some(expected) = &expected {
                        assert_eq!(expected, &packet);
                    } else {
                        expected = Some(packet);
                    }
                    if !next_permutation(&mut order) {
                        break;
                    }
                }
            }
        }
    }
}

fn next_permutation(values: &mut [usize]) -> bool {
    let Some(pivot) = (0..values.len().saturating_sub(1))
        .rev()
        .find(|index| values[*index] < values[*index + 1])
    else {
        return false;
    };
    let swap = (pivot + 1..values.len())
        .rev()
        .find(|index| values[*index] > values[pivot])
        .expect("permutation successor");
    values.swap(pivot, swap);
    values[pivot + 1..].reverse();
    true
}

fn canonical_digest(value: &str) -> ContractDigestV1 {
    ContractDigestV1::from_digest(digest(value))
        .unwrap_or_else(|error| panic!("valid canonical digest: {error}"))
}

fn canonical_context(
    legacy: &RecallPacketV1,
    candidate_count: u16,
) -> CanonicalRecallShadowContextV1 {
    let selection_bindings = legacy
        .selections
        .iter()
        .enumerate()
        .map(|(index, selection)| CanonicalRecallSelectionBindingV1 {
            legacy_record_id: selection.record_id.clone(),
            legacy_record_revision: selection.record_revision,
            legacy_record_digest: selection.record_digest,
            canonical_event: CanonicalSelectedEventRefV1 {
                event_id: ContractIdV1::new(format!("event:{}", index + 1))
                    .unwrap_or_else(|error| panic!("valid canonical event id: {error}")),
                revision: selection.record_revision.get(),
                event_digest: canonical_digest(&format!("canonical-event-{index}")),
            },
        })
        .collect();
    CanonicalRecallShadowContextV1 {
        legacy_cue_digest: legacy.cue_digest,
        legacy_candidate_union_digest: legacy.candidate_union_digest,
        legacy_generation_vector_digest: legacy.generation_vector_digest,
        canonical_cue_digest: canonical_digest("canonical-cue"),
        selection_bindings,
        event_snapshot_digest: canonical_digest("event-snapshot"),
        engram_snapshot_digest: canonical_digest("engram-snapshot"),
        active_nodes: Vec::new(),
        activation_paths: Vec::new(),
        contradictions: Vec::new(),
        coverage_ppm: 900_000,
        confidence_ppm: 800_000,
        ood_ppm: 100_000,
        resource_receipt: CanonicalRecallResourceReceiptV1 {
            candidate_event_count: candidate_count,
            node_count: 0,
            synapse_count: 0,
            active_node_count: 0,
            settling_steps: 0,
        },
    }
}

#[test]
fn legacy_recall_projects_to_canonical_shadow_without_fabricating_authority() {
    let cue = cue();
    let policy = policy();
    let first = record(1);
    let second = record(2);
    let legacy = recall(
        &cue,
        &policy,
        vec![
            candidate(first.clone(), RetrievalChannelV1::Lexical, 1),
            candidate(first, RetrievalChannelV1::Entity, 1),
            candidate(second.clone(), RetrievalChannelV1::Lexical, 2),
            candidate(second, RetrievalChannelV1::Entity, 2),
        ],
    )
    .unwrap_or_else(|error| panic!("legacy recall: {error}"));

    let canonical = adapt_generation_bound_recall_to_canonical_shadow_v1(
        &legacy,
        canonical_context(&legacy, 2),
    )
    .unwrap_or_else(|error| panic!("canonical shadow projection: {error}"));

    assert_eq!(canonical.cue_digest, canonical_digest("canonical-cue"));
    assert_ne!(canonical.cue_digest.digest(), legacy.cue_digest);
    assert_eq!(canonical.selected_events.len(), legacy.selections.len());
    assert!(canonical.abstain.is_none());
    assert!(
        canonical
            .selected_events
            .windows(2)
            .all(|rows| rows[0] < rows[1])
    );
}

#[test]
fn legacy_abstention_maps_to_canonical_abstention_without_selected_events() {
    let cue = cue();
    let policy = policy();
    let legacy = recall(
        &cue,
        &policy,
        vec![candidate(record(1), RetrievalChannelV1::Lexical, 1)],
    )
    .unwrap_or_else(|error| panic!("legacy abstention: {error}"));

    let canonical = adapt_generation_bound_recall_to_canonical_shadow_v1(
        &legacy,
        canonical_context(&legacy, 1),
    )
    .unwrap_or_else(|error| panic!("canonical abstention: {error}"));

    assert_eq!(
        canonical.abstain,
        Some(CanonicalRecallAbstainReasonV1::InsufficientCoverage)
    );
    assert!(canonical.selected_events.is_empty());
}

#[test]
fn canonical_shadow_receipt_cannot_undercount_legacy_selection() {
    let cue = cue();
    let policy = policy();
    let first = record(1);
    let second = record(2);
    let legacy = recall(
        &cue,
        &policy,
        vec![
            candidate(first.clone(), RetrievalChannelV1::Lexical, 1),
            candidate(first, RetrievalChannelV1::Entity, 1),
            candidate(second.clone(), RetrievalChannelV1::Lexical, 2),
            candidate(second, RetrievalChannelV1::Entity, 2),
        ],
    )
    .unwrap_or_else(|error| panic!("legacy recall: {error}"));

    assert_eq!(
        adapt_generation_bound_recall_to_canonical_shadow_v1(
            &legacy,
            canonical_context(&legacy, 1),
        ),
        Err(RecallErrorV1::CanonicalAdapter(
            "candidate receipt undercounts legacy selected plus omitted events"
        ))
    );
}

#[test]
fn canonical_shadow_bridge_rejects_cross_packet_or_selection_drift() {
    let cue = cue();
    let policy = policy();
    let first = record(1);
    let second = record(2);
    let legacy = recall(
        &cue,
        &policy,
        vec![
            candidate(first.clone(), RetrievalChannelV1::Lexical, 1),
            candidate(first, RetrievalChannelV1::Entity, 1),
            candidate(second.clone(), RetrievalChannelV1::Lexical, 2),
            candidate(second, RetrievalChannelV1::Entity, 2),
        ],
    )
    .unwrap_or_else(|error| panic!("legacy recall: {error}"));

    let mut wrong_packet = canonical_context(&legacy, 2);
    wrong_packet.legacy_cue_digest = digest("different-legacy-cue");
    assert_eq!(
        adapt_generation_bound_recall_to_canonical_shadow_v1(&legacy, wrong_packet),
        Err(RecallErrorV1::CanonicalAdapter(
            "canonical shadow context is bound to a different legacy packet"
        ))
    );

    let mut wrong_selection = canonical_context(&legacy, 2);
    wrong_selection.selection_bindings[0].legacy_record_digest = digest("drifted-record");
    assert_eq!(
        adapt_generation_bound_recall_to_canonical_shadow_v1(&legacy, wrong_selection),
        Err(RecallErrorV1::CanonicalAdapter(
            "missing exact canonical binding for legacy selection"
        ))
    );
}

use super::*;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

fn digest(value: &str) -> Digest32 { Digest32::of_bytes(value.as_bytes()) }
fn id(value: &str) -> StableId { StableId::new(value).expect("id") }
fn cue() -> MemoryCueV1 {
    let d = digest("explicit-evidence-fixture");
    MemoryCueV1 {
        cue_id: id("cue:explicit"), objective_digest: d, approved_context_digest: d,
        request_digest: d, cue_profile_digest: d,
        snapshot_key: CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
            scope_id: id("scope:explicit"), purpose_id: id("purpose:recall"),
            memory_ledger_frontier: 1, knowledge_fact_frontier: 1,
            tombstone_frontier: 1, source_ledger_frontier: 1,
            knowledge_graph_generation: Generation::new(1).expect("generation"),
            compact_checkpoint_generation: Generation::new(1).expect("generation"),
            prompt_registry_revision: Revision::new(1).expect("revision"),
            retrieval_profile_digest: d, encoder_preprocessor_digest: d, authority_epoch: 1,
            model_digest: d, tokenizer_digest: d, template_digest: d, tool_schema_digest: d,
        }).expect("snapshot"),
    }
}
fn candidate(number: u32, channel: RetrievalChannelV1, polarity: ContradictionPolarityV1) -> RetrievalChannelCandidateV1 {
    RetrievalChannelCandidateV1 {
        record: MemoryRecord {
            record_id: id(&format!("memory:{number}")), revision: Revision::new(1).expect("revision"),
            kind: MemoryKind::Fact, content_digest: digest(&format!("content:{number}")),
            predecessor_digest: None, citations: Vec::new(), state: RecordState::Live,
        },
        channel, channel_rank: number, normalized_score: FixedQ32::ONE,
        ood: ProbabilityQ32::ZERO, support_digest: digest(&format!("support:{number}")),
        contradiction_evidence: vec![ContradictionEvidenceV1 { proposition_digest: digest("one-proposition"), polarity }],
        // Deliberately no legacy group: real semantics do not depend on it.
        contradiction_group_digest: None,
        generation_vector_digest: cue().snapshot_key.vector_digest,
    }
}
fn policy(weight: FixedQ32) -> RetrievalPolicyV1 {
    RetrievalPolicyV1 {
        policy_id: id("policy:explicit"),
        channel_weights: vec![RetrievalChannelV1::Lexical, RetrievalChannelV1::Entity, RetrievalChannelV1::ContradictionSupport]
            .into_iter().map(|channel| RetrievalChannelWeightV1 { channel, weight, maximum_candidates: 16 }).collect(),
        maximum_results: 8, minimum_total_score: FixedQ32::ZERO,
        maximum_ood: ProbabilityQ32::ONE, minimum_distinct_channels: 1, abstain_on_contradiction: true,
    }
}

#[test]
fn one_record_across_channels_never_acquires_an_opposite_stance() {
    let candidates = vec![
        candidate(1, RetrievalChannelV1::Lexical, ContradictionPolarityV1::Supports),
        candidate(1, RetrievalChannelV1::ContradictionSupport, ContradictionPolarityV1::Supports),
    ];
    let packet = recall(&cue(), &policy(FixedQ32::ONE), candidates).expect("recall");
    assert_eq!(packet.disposition, RecallDispositionV1::Recalled);
    assert_eq!(packet.selections.len(), 1);
    assert_eq!(packet.selections[0].contradiction_evidence.len(), 1);
}

#[test]
fn opposite_stances_in_the_same_channel_are_not_missed() {
    let packet = recall(&cue(), &policy(FixedQ32::ONE), vec![
        candidate(1, RetrievalChannelV1::Lexical, ContradictionPolarityV1::Supports),
        candidate(2, RetrievalChannelV1::Lexical, ContradictionPolarityV1::Opposes),
    ]).expect("explicit disposition");
    assert_eq!(packet.disposition, RecallDispositionV1::Abstained(RecallAbstentionReasonV1::ContradictoryEvidence));
}

#[test]
fn unrelated_propositions_do_not_form_a_cartesian_conflict() {
    let positive = candidate(1, RetrievalChannelV1::Lexical, ContradictionPolarityV1::Supports);
    let mut negative = candidate(1, RetrievalChannelV1::ContradictionSupport, ContradictionPolarityV1::Opposes);
    negative.contradiction_evidence[0].proposition_digest = digest("different-proposition");
    let packet = recall(&cue(), &policy(FixedQ32::ONE), vec![positive, negative]).expect("recall");
    assert_eq!(packet.disposition, RecallDispositionV1::Recalled);
    assert_eq!(packet.selections[0].contradiction_evidence.len(), 2);
}

#[test]
fn evidence_tampering_changes_union_and_packet_commitments() {
    let p = policy(FixedQ32::ONE);
    let input = vec![candidate(1, RetrievalChannelV1::Lexical, ContradictionPolarityV1::Supports)];
    let mut union = build_candidate_union(&cue(), &p, input.clone()).expect("union");
    union.entries[0].contradiction_evidence[0].polarity = ContradictionPolarityV1::Opposes;
    assert!(matches!(union.validate(), Err(RecallErrorV1::DigestMismatch(_))));
    let mut packet = recall(&cue(), &p, input).expect("recall");
    packet.selections[0].contradiction_evidence[0].polarity = ContradictionPolarityV1::Opposes;
    assert!(matches!(packet.validate(), Err(RecallErrorV1::DigestMismatch(_))));
}

#[test]
fn malformed_explicit_evidence_is_rejected_before_disabled_channel_filtering() {
    let mut p = policy(FixedQ32::ONE);
    p.channel_weights[2].weight = FixedQ32::ZERO;
    let mut c = candidate(1, RetrievalChannelV1::ContradictionSupport, ContradictionPolarityV1::Supports);
    c.contradiction_evidence[0].proposition_digest = Digest32::ZERO;
    assert!(build_candidate_union(&cue(), &p, vec![c]).is_err());
}

#[test]
fn property_stance_and_order_are_independent_of_channels_and_policy_weights() {
    let channels = [RetrievalChannelV1::Lexical, RetrievalChannelV1::Entity, RetrievalChannelV1::ContradictionSupport];
    let weights = [FixedQ32::from_raw(1), FixedQ32::from_raw(1_i64 << 29), FixedQ32::ONE];
    for weight in weights {
        for left in channels {
            for right in channels {
                for polarity in [ContradictionPolarityV1::Supports, ContradictionPolarityV1::Opposes] {
                    let input = vec![candidate(1, left, polarity), candidate(2, right, polarity)];
                    let mut reverse = input.clone(); reverse.reverse();
                    let p = policy(weight);
                    let a = recall(&cue(), &p, input).expect("recall");
                    let b = recall(&cue(), &p, reverse).expect("reverse recall");
                    assert_eq!(a, b);
                    assert_eq!(a.disposition, RecallDispositionV1::Recalled);
                    assert_eq!(a.selections.len() + a.omitted_count as usize, 2);
                }
            }
        }
    }
}

#[test]
fn zero_score_never_becomes_admitted_support_at_a_zero_floor() {
    let mut c = candidate(1, RetrievalChannelV1::Lexical, ContradictionPolarityV1::Supports);
    c.normalized_score = FixedQ32::ZERO;
    let packet = recall(&cue(), &policy(FixedQ32::ONE), vec![c]).expect("abstention");
    assert_eq!(packet.disposition, RecallDispositionV1::Abstained(RecallAbstentionReasonV1::ScoreBelowFloor));
}

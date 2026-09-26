use super::*;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn revision(value: u64) -> Revision {
    Revision::new(value).expect("revision")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn cue() -> MemoryCueV1 {
    MemoryCueV1 {
        cue_id: id("cue:semantic-v2"),
        objective_digest: digest("objective"),
        approved_context_digest: digest("approved-context"),
        request_digest: digest("request"),
        snapshot_key: CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
            scope_id: id("scope:semantic-v2"),
            purpose_id: id("purpose:recall"),
            memory_ledger_frontier: 11,
            knowledge_fact_frontier: 9,
            tombstone_frontier: 3,
            source_ledger_frontier: 12,
            knowledge_graph_generation: generation(2),
            compact_checkpoint_generation: generation(1),
            prompt_registry_revision: revision(4),
            retrieval_profile_digest: digest("retrieval-profile"),
            encoder_preprocessor_digest: digest("encoder-profile"),
            authority_epoch: 7,
            model_digest: digest("model"),
            tokenizer_digest: digest("tokenizer"),
            template_digest: digest("template"),
            tool_schema_digest: digest("tool-schema"),
        })
        .expect("snapshot key"),
        cue_profile_digest: digest("cue-profile"),
    }
}

fn record(number: u64) -> MemoryRecord {
    MemoryRecord {
        record_id: id(&format!("memory:{number}")),
        revision: revision(1),
        kind: MemoryKind::Fact,
        content_digest: digest(&format!("content:{number}")),
        predecessor_digest: None,
        citations: Vec::new(),
        state: RecordState::Live,
    }
}

fn candidate(
    number: u64,
    channel: RetrievalChannelV1,
    score: FixedQ32,
    ood: ProbabilityQ32,
    proposition: Option<Digest32>,
) -> RetrievalChannelCandidateV1 {
    RetrievalChannelCandidateV1 {
        record: record(number),
        channel,
        channel_rank: 1,
        normalized_score: score,
        ood,
        support_digest: digest(&format!("support:{number}:{channel:?}")),
        contradiction_group_digest: proposition,
        generation_vector_digest: cue().snapshot_key.vector_digest,
    }
}

fn policy(rows: Vec<(RetrievalChannelV1, FixedQ32)>) -> RetrievalPolicyV1 {
    RetrievalPolicyV1 {
        policy_id: id("policy:semantic-v2"),
        channel_weights: rows
            .into_iter()
            .map(|(channel, weight)| RetrievalChannelWeightV1 {
                channel,
                weight,
                maximum_candidates: 16,
            })
            .collect(),
        maximum_results: 8,
        minimum_total_score: FixedQ32::ZERO,
        maximum_ood: ProbabilityQ32::ONE,
        minimum_distinct_channels: 1,
        abstain_on_contradiction: true,
    }
}

#[test]
fn multiple_same_side_contradiction_support_candidates_do_not_abstain() {
    let proposition = digest("proposition:alpha");
    let candidates = vec![
        candidate(
            1,
            RetrievalChannelV1::ContradictionSupport,
            FixedQ32::ONE,
            ProbabilityQ32::ZERO,
            Some(proposition),
        ),
        candidate(
            2,
            RetrievalChannelV1::ContradictionSupport,
            FixedQ32::ONE,
            ProbabilityQ32::ZERO,
            Some(proposition),
        ),
    ];
    let packet = recall(
        &cue(),
        &policy(vec![(
            RetrievalChannelV1::ContradictionSupport,
            FixedQ32::ONE,
        )]),
        candidates,
    )
    .expect("same-side evidence is valid");
    assert_eq!(packet.disposition, RecallDispositionV1::Recalled);
    assert_eq!(packet.selections.len(), 2);
}

#[test]
fn opposite_polarities_for_one_proposition_force_abstention() {
    let proposition = digest("proposition:beta");
    let packet = recall(
        &cue(),
        &policy(vec![
            (RetrievalChannelV1::Lexical, FixedQ32::ONE),
            (
                RetrievalChannelV1::ContradictionSupport,
                FixedQ32::ONE,
            ),
        ]),
        vec![
            candidate(
                1,
                RetrievalChannelV1::Lexical,
                FixedQ32::ONE,
                ProbabilityQ32::ZERO,
                Some(proposition),
            ),
            candidate(
                2,
                RetrievalChannelV1::ContradictionSupport,
                FixedQ32::ONE,
                ProbabilityQ32::ZERO,
                Some(proposition),
            ),
        ],
    )
    .expect("opposite evidence produces an explicit disposition");
    assert_eq!(
        packet.disposition,
        RecallDispositionV1::Abstained(RecallAbstentionReasonV1::ContradictoryEvidence)
    );
}

#[test]
fn low_score_high_ood_candidate_cannot_poison_admitted_result() {
    let mut retrieval_policy = policy(vec![(RetrievalChannelV1::Lexical, FixedQ32::ONE)]);
    retrieval_policy.minimum_total_score = FixedQ32::from_raw(1_i64 << 31);
    retrieval_policy.maximum_ood = ProbabilityQ32::from_raw(1_u64 << 30).expect("probability");
    let packet = recall(
        &cue(),
        &retrieval_policy,
        vec![
            candidate(
                1,
                RetrievalChannelV1::Lexical,
                FixedQ32::ONE,
                ProbabilityQ32::ZERO,
                None,
            ),
            candidate(
                2,
                RetrievalChannelV1::Lexical,
                FixedQ32::from_raw(1),
                ProbabilityQ32::ONE,
                None,
            ),
        ],
    )
    .expect("admitted recall");
    assert_eq!(packet.disposition, RecallDispositionV1::Recalled);
    assert_eq!(packet.selections.len(), 1);
    assert_eq!(packet.selections[0].record_id, id("memory:1"));
    assert_eq!(packet.omitted_count, 0);
}

#[test]
fn low_score_opposing_candidate_cannot_poison_admitted_result() {
    let proposition = digest("proposition:gamma");
    let mut retrieval_policy = policy(vec![
        (RetrievalChannelV1::Lexical, FixedQ32::ONE),
        (
            RetrievalChannelV1::ContradictionSupport,
            FixedQ32::ONE,
        ),
    ]);
    retrieval_policy.minimum_total_score = FixedQ32::from_raw(1_i64 << 31);
    let packet = recall(
        &cue(),
        &retrieval_policy,
        vec![
            candidate(
                1,
                RetrievalChannelV1::Lexical,
                FixedQ32::ONE,
                ProbabilityQ32::ZERO,
                Some(proposition),
            ),
            candidate(
                2,
                RetrievalChannelV1::ContradictionSupport,
                FixedQ32::from_raw(1),
                ProbabilityQ32::ZERO,
                Some(proposition),
            ),
        ],
    )
    .expect("admitted recall");
    assert_eq!(packet.disposition, RecallDispositionV1::Recalled);
    assert_eq!(packet.selections.len(), 1);
    assert_eq!(packet.selections[0].record_id, id("memory:1"));
}

#[test]
fn zero_weight_contradiction_channel_has_no_semantic_effect() {
    let proposition = digest("proposition:delta");
    let packet = recall(
        &cue(),
        &policy(vec![
            (RetrievalChannelV1::Lexical, FixedQ32::ONE),
            (
                RetrievalChannelV1::ContradictionSupport,
                FixedQ32::ZERO,
            ),
        ]),
        vec![
            candidate(
                1,
                RetrievalChannelV1::Lexical,
                FixedQ32::ONE,
                ProbabilityQ32::ZERO,
                Some(proposition),
            ),
            candidate(
                2,
                RetrievalChannelV1::ContradictionSupport,
                FixedQ32::ONE,
                ProbabilityQ32::ONE,
                Some(proposition),
            ),
        ],
    )
    .expect("zero-weight evidence is excluded");
    assert_eq!(packet.disposition, RecallDispositionV1::Recalled);
    assert_eq!(packet.selections.len(), 1);
    assert_eq!(packet.selections[0].record_id, id("memory:1"));
    assert_eq!(packet.distinct_channels, 1);
}

#[test]
fn property_permutations_preserve_proposition_aware_recall() {
    let proposition = digest("proposition:epsilon");
    let candidates = [
        candidate(
            1,
            RetrievalChannelV1::Lexical,
            FixedQ32::ONE,
            ProbabilityQ32::ZERO,
            Some(proposition),
        ),
        candidate(
            2,
            RetrievalChannelV1::Entity,
            FixedQ32::from_raw(3_i64 << 30),
            ProbabilityQ32::ZERO,
            Some(proposition),
        ),
        candidate(
            3,
            RetrievalChannelV1::ContradictionSupport,
            FixedQ32::from_raw(1),
            ProbabilityQ32::ONE,
            Some(proposition),
        ),
    ];
    let mut retrieval_policy = policy(vec![
        (RetrievalChannelV1::Lexical, FixedQ32::ONE),
        (RetrievalChannelV1::Entity, FixedQ32::ONE),
        (
            RetrievalChannelV1::ContradictionSupport,
            FixedQ32::ONE,
        ),
    ]);
    retrieval_policy.minimum_total_score = FixedQ32::from_raw(1_i64 << 31);
    retrieval_policy.maximum_ood = ProbabilityQ32::from_raw(1_u64 << 30).expect("probability");

    let mut order = vec![0_usize, 1, 2];
    let mut expected = None;
    loop {
        let packet = recall(
            &cue(),
            &retrieval_policy,
            order
                .iter()
                .map(|index| candidates[*index].clone())
                .collect(),
        )
        .expect("permutation recall");
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
        .expect("successor");
    values.swap(pivot, swap);
    values[pivot + 1..].reverse();
    true
}

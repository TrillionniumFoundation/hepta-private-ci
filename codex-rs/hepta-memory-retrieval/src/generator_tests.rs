use super::*;

use crate::RetrievalChannelWeightV1;
use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;

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

fn snapshot_key() -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:generator"),
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
    compile_cue(
        id("cue:generator"),
        digest("objective"),
        digest("approved-context"),
        digest("request"),
        snapshot_key(),
        digest("cue-profile"),
    )
    .unwrap_or_else(|error| panic!("valid cue: {error}"))
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
    support: &str,
) -> RetrievalChannelCandidateV1 {
    RetrievalChannelCandidateV1 {
        record,
        channel,
        channel_rank: rank,
        normalized_score: FixedQ32::ONE,
        ood: ProbabilityQ32::ZERO,
        support_digest: digest(support),
        contradiction_group_digest: None,
        generation_vector_digest: cue().snapshot_key.vector_digest,
    }
}

fn batch(
    generator: RetrievalGeneratorOwnerV1,
    candidates: Vec<RetrievalChannelCandidateV1>,
    completeness: RetrievalSourceCompletenessV1,
) -> RetrievalGeneratorBatchV1 {
    let receipt = RetrievalGeneratorReceiptV1::new(
        generator,
        cue().snapshot_key.vector_digest,
        digest(&format!("owner-generation-{generator:?}")),
        u32::try_from(candidates.len()).unwrap_or(u32::MAX),
        completeness,
    )
    .unwrap_or_else(|error| panic!("valid receipt: {error}"));
    RetrievalGeneratorBatchV1 {
        receipt,
        candidates,
    }
}

fn policy() -> RetrievalPolicyV1 {
    RetrievalPolicyV1 {
        policy_id: id("policy:generator"),
        channel_weights: vec![
            RetrievalChannelWeightV1 {
                channel: RetrievalChannelV1::Lexical,
                weight: FixedQ32::ONE,
                maximum_candidates: 16,
            },
            RetrievalChannelWeightV1 {
                channel: RetrievalChannelV1::Entity,
                weight: FixedQ32::ONE,
                maximum_candidates: 16,
            },
            RetrievalChannelWeightV1 {
                channel: RetrievalChannelV1::Temporal,
                weight: FixedQ32::ONE,
                maximum_candidates: 16,
            },
        ],
        maximum_results: 8,
        minimum_total_score: FixedQ32::from_raw(1),
        maximum_ood: ProbabilityQ32::ONE,
        minimum_distinct_channels: 2,
        abstain_on_contradiction: true,
    }
}

fn lexical_policy() -> RetrievalPolicyV1 {
    RetrievalPolicyV1 {
        policy_id: id("policy:lexical"),
        channel_weights: vec![RetrievalChannelWeightV1 {
            channel: RetrievalChannelV1::Lexical,
            weight: FixedQ32::ONE,
            maximum_candidates: 16,
        }],
        maximum_results: 8,
        minimum_total_score: FixedQ32::from_raw(1),
        maximum_ood: ProbabilityQ32::ONE,
        minimum_distinct_channels: 1,
        abstain_on_contradiction: true,
    }
}

#[test]
fn compile_cue_is_the_validated_constructor() {
    let cue = cue();
    cue.validate().expect("compiled cue validates");
    assert_eq!(cue.snapshot_key, snapshot_key());
    assert_eq!(
        compile_cue(
            id("cue:bad"),
            Digest32::ZERO,
            digest("context"),
            digest("request"),
            snapshot_key(),
            digest("profile"),
        ),
        Err(RecallErrorV1::EmptyDigest("objective"))
    );
}

#[test]
fn generator_completeness_is_bound_even_with_identical_candidates() {
    let record = record(1);
    let exhausted = GeneratedCandidateInputV1::new(vec![batch(
        RetrievalGeneratorOwnerV1::CognitiveLexical,
        vec![candidate(
            record.clone(),
            RetrievalChannelV1::Lexical,
            1,
            "support",
        )],
        RetrievalSourceCompletenessV1::Exhausted,
    )])
    .expect("exhausted input");
    let limited = GeneratedCandidateInputV1::new(vec![batch(
        RetrievalGeneratorOwnerV1::CognitiveLexical,
        vec![candidate(record, RetrievalChannelV1::Lexical, 1, "support")],
        RetrievalSourceCompletenessV1::LimitReached,
    )])
    .expect("limited input");
    assert_ne!(
        exhausted.source_completeness_digest,
        limited.source_completeness_digest
    );
}

#[test]
fn associative_and_entity_owner_batches_merge_without_double_counting_channel() {
    let record = record(1);
    let input = GeneratedCandidateInputV1::new(vec![
        batch(
            RetrievalGeneratorOwnerV1::CognitiveEntity,
            vec![candidate(
                record.clone(),
                RetrievalChannelV1::Entity,
                2,
                "entity-support",
            )],
            RetrievalSourceCompletenessV1::Exhausted,
        ),
        batch(
            RetrievalGeneratorOwnerV1::CognitiveAssociative,
            vec![candidate(
                record,
                RetrievalChannelV1::Graph,
                1,
                "graph-support",
            )],
            RetrievalSourceCompletenessV1::Exhausted,
        ),
    ])
    .expect("merged input");
    let flattened = input.flattened_candidates().expect("flatten");
    assert_eq!(flattened.len(), 2);
    assert_eq!(flattened[0].channel, RetrievalChannelV1::Entity);
    assert_eq!(flattened[1].channel, RetrievalChannelV1::Graph);
}

#[test]
fn tampered_generator_receipt_fails_closed() {
    let mut receipt = RetrievalGeneratorReceiptV1::new(
        RetrievalGeneratorOwnerV1::CognitiveTemporal,
        cue().snapshot_key.vector_digest,
        digest("owner-generation"),
        0,
        RetrievalSourceCompletenessV1::Exhausted,
    )
    .expect("receipt");
    receipt.candidate_count = 1;
    assert_eq!(
        receipt.validate(),
        Err(GeneratorErrorV1::DigestMismatch("generator_receipt"))
    );
}

#[test]
fn generator_rank_and_total_candidate_bounds_fail_closed() {
    let invalid_rank = batch(
        RetrievalGeneratorOwnerV1::CognitiveLexical,
        vec![candidate(
            record(1),
            RetrievalChannelV1::Lexical,
            2,
            "rank-out-of-range",
        )],
        RetrievalSourceCompletenessV1::Exhausted,
    );
    assert_eq!(
        invalid_rank.validate(),
        Err(GeneratorErrorV1::ChannelRankOutOfRange)
    );

    let lexical = (1..=256_u64)
        .map(|number| {
            candidate(
                record(number),
                RetrievalChannelV1::Lexical,
                u32::try_from(number).expect("rank"),
                "lexical",
            )
        })
        .collect::<Vec<_>>();
    let entity = (257..=513_u64)
        .enumerate()
        .map(|(index, number)| {
            candidate(
                record(number),
                RetrievalChannelV1::Entity,
                u32::try_from(index + 1).expect("rank"),
                "entity",
            )
        })
        .collect::<Vec<_>>();
    assert_eq!(
        GeneratedCandidateInputV1::new(vec![
            batch(
                RetrievalGeneratorOwnerV1::CognitiveLexical,
                lexical,
                RetrievalSourceCompletenessV1::LimitReached,
            ),
            batch(
                RetrievalGeneratorOwnerV1::CognitiveEntity,
                entity,
                RetrievalSourceCompletenessV1::LimitReached,
            ),
        ]),
        Err(GeneratorErrorV1::CandidateLimitExceeded)
    );
}

#[test]
fn generated_receipt_rejects_cross_generation_rebinding() {
    let input = GeneratedCandidateInputV1::new(vec![batch(
        RetrievalGeneratorOwnerV1::CognitiveLexical,
        vec![candidate(
            record(1),
            RetrievalChannelV1::Lexical,
            1,
            "support",
        )],
        RetrievalSourceCompletenessV1::Exhausted,
    )])
    .expect("input");
    let cue = cue();
    let mut generated = build_candidate_union_from_generated(&cue, &lexical_policy(), &input)
        .expect("generated union");

    let replacement = RetrievalGeneratorReceiptV1::new(
        RetrievalGeneratorOwnerV1::CognitiveLexical,
        digest("different-generation"),
        digest("different-owner-generation"),
        1,
        RetrievalSourceCompletenessV1::Exhausted,
    )
    .expect("replacement receipt");
    generated.generator_receipts = vec![replacement];
    let mut bytes = SOURCE_COMPLETENESS_DOMAIN.to_vec();
    push_len(&mut bytes, generated.generator_receipts.len());
    push_digest(&mut bytes, generated.generator_receipts[0].receipt_digest);
    generated.source_completeness_digest = Digest32::of_bytes(&bytes);
    generated.receipt_digest = generated.compute_receipt_digest();
    assert_eq!(
        generated.validate(),
        Err(GeneratorErrorV1::GenerationVectorMismatch)
    );
}

#[test]
fn active_policy_requires_exact_owner_generator_coverage() {
    let input = GeneratedCandidateInputV1::new(vec![batch(
        RetrievalGeneratorOwnerV1::CognitiveLexical,
        vec![candidate(
            record(1),
            RetrievalChannelV1::Lexical,
            1,
            "lexical-only",
        )],
        RetrievalSourceCompletenessV1::Exhausted,
    )])
    .expect("input");
    assert_eq!(
        build_candidate_union_from_generated(&cue(), &policy(), &input),
        Err(GeneratorErrorV1::MissingGeneratorForChannel(
            RetrievalChannelV1::Entity
        ))
    );

    let input = GeneratedCandidateInputV1::new(vec![
        batch(
            RetrievalGeneratorOwnerV1::CognitiveLexical,
            vec![candidate(
                record(1),
                RetrievalChannelV1::Lexical,
                1,
                "lexical",
            )],
            RetrievalSourceCompletenessV1::Exhausted,
        ),
        batch(
            RetrievalGeneratorOwnerV1::CognitiveEntity,
            Vec::new(),
            RetrievalSourceCompletenessV1::Exhausted,
        ),
    ])
    .expect("input");
    assert_eq!(
        build_candidate_union_from_generated(&cue(), &lexical_policy(), &input),
        Err(GeneratorErrorV1::UnexpectedGeneratorForChannel(
            RetrievalChannelV1::Entity
        ))
    );
}

#[test]
fn property_all_generator_batch_permutations_have_one_recall() {
    let first = record(1);
    let second = record(2);
    let batches = vec![
        batch(
            RetrievalGeneratorOwnerV1::CognitiveLexical,
            vec![
                candidate(first.clone(), RetrievalChannelV1::Lexical, 1, "lexical-1"),
                candidate(second.clone(), RetrievalChannelV1::Lexical, 2, "lexical-2"),
            ],
            RetrievalSourceCompletenessV1::Exhausted,
        ),
        batch(
            RetrievalGeneratorOwnerV1::CognitiveEntity,
            vec![
                candidate(first.clone(), RetrievalChannelV1::Entity, 1, "entity-1"),
                candidate(second.clone(), RetrievalChannelV1::Entity, 2, "entity-2"),
            ],
            RetrievalSourceCompletenessV1::LimitReached,
        ),
        batch(
            RetrievalGeneratorOwnerV1::CognitiveTemporal,
            vec![candidate(
                second,
                RetrievalChannelV1::Temporal,
                1,
                "temporal-2",
            )],
            RetrievalSourceCompletenessV1::Exhausted,
        ),
    ];
    let cue = cue();
    let policy = policy();
    let mut order = vec![0_usize, 1, 2];
    let mut expected = None;
    loop {
        let input = GeneratedCandidateInputV1::new(
            order.iter().map(|index| batches[*index].clone()).collect(),
        )
        .expect("input");
        let recall = recall_generated(&cue, &policy, &input).expect("recall");
        if let Some(expected) = &expected {
            assert_eq!(expected, &recall);
        } else {
            expected = Some(recall);
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
        .expect("permutation successor");
    values.swap(pivot, swap);
    values[pivot + 1..].reverse();
    true
}

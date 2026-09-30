use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use super::*;
use crate::RetrievalChannelCandidateV1;
use crate::RetrievalGeneratorBatchV1;
use crate::RetrievalGeneratorReceiptV1;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn candidate(
    generator: RetrievalGeneratorOwnerV1,
    generation: Digest32,
) -> RetrievalChannelCandidateV1 {
    RetrievalChannelCandidateV1 {
        record: MemoryRecord {
            record_id: StableId::new("memory:product-admission").expect("stable record id"),
            revision: Revision::new(1).expect("revision"),
            kind: MemoryKind::Fact,
            content_digest: digest(&format!("content:{generator:?}")),
            predecessor_digest: None,
            citations: Vec::new(),
            state: RecordState::Live,
        },
        channel: generator.channel(),
        channel_rank: 1,
        normalized_score: FixedQ32::ONE,
        ood: ProbabilityQ32::ZERO,
        support_digest: digest(&format!("support:{generator:?}")),
        contradiction_group_digest: None,
        generation_vector_digest: generation,
    }
}

fn batch(
    generator: RetrievalGeneratorOwnerV1,
    completeness: RetrievalSourceCompletenessV1,
) -> RetrievalGeneratorBatchV1 {
    let generation = digest("generation");
    let candidates = if completeness == RetrievalSourceCompletenessV1::Unavailable {
        Vec::new()
    } else {
        vec![candidate(generator, generation)]
    };
    let receipt = RetrievalGeneratorReceiptV1::new(
        generator,
        generation,
        digest(&format!("owner-generation:{generator:?}")),
        u32::try_from(candidates.len()).expect("candidate count"),
        completeness,
    )
    .expect("generator receipt");
    RetrievalGeneratorBatchV1 {
        receipt,
        candidates,
    }
}

fn row(
    generator: RetrievalGeneratorOwnerV1,
    on_limit_reached: IncompleteSourceActionV1,
    on_unavailable: IncompleteSourceActionV1,
) -> RetrievalCompletenessPolicyRowV1 {
    RetrievalCompletenessPolicyRowV1 {
        generator,
        on_limit_reached,
        on_unavailable,
    }
}

#[test]
fn limit_reached_is_an_explicit_degraded_decision() {
    let input = GeneratedCandidateInputV1::new(vec![batch(
        RetrievalGeneratorOwnerV1::CognitiveLexical,
        RetrievalSourceCompletenessV1::LimitReached,
    )])
    .expect("input");
    let policy = RetrievalCompletenessPolicyV1::new(vec![row(
        RetrievalGeneratorOwnerV1::CognitiveLexical,
        IncompleteSourceActionV1::Degrade,
        IncompleteSourceActionV1::Abstain,
    )])
    .expect("policy");
    let validated = ValidatedCandidateSetV1::new(input, &policy).expect("validated");

    assert!(validated.completeness().permits_recall());
    assert!(matches!(
        validated.completeness(),
        RetrievalCompletenessDecisionV1::Degraded { incomplete_sources }
            if incomplete_sources.len() == 1
                && incomplete_sources[0].completeness
                    == RetrievalSourceCompletenessV1::LimitReached
    ));
}

#[test]
fn required_incomplete_owner_abstains_without_partial_recall() {
    let input = GeneratedCandidateInputV1::new(vec![batch(
        RetrievalGeneratorOwnerV1::KnowledgeGraphCausal,
        RetrievalSourceCompletenessV1::LimitReached,
    )])
    .expect("input");
    let policy = RetrievalCompletenessPolicyV1::new(vec![row(
        RetrievalGeneratorOwnerV1::KnowledgeGraphCausal,
        IncompleteSourceActionV1::Abstain,
        IncompleteSourceActionV1::FailClosed,
    )])
    .expect("policy");
    let validated = ValidatedCandidateSetV1::new(input, &policy).expect("validated");

    assert!(!validated.completeness().permits_recall());
    assert!(matches!(
        validated.completeness(),
        RetrievalCompletenessDecisionV1::Abstain { .. }
    ));
}

#[test]
fn authority_critical_unavailability_is_fail_closed() {
    let input = GeneratedCandidateInputV1::new(vec![batch(
        RetrievalGeneratorOwnerV1::KnowledgeGraphContradiction,
        RetrievalSourceCompletenessV1::Unavailable,
    )])
    .expect("input");
    let policy = RetrievalCompletenessPolicyV1::new(vec![row(
        RetrievalGeneratorOwnerV1::KnowledgeGraphContradiction,
        IncompleteSourceActionV1::Abstain,
        IncompleteSourceActionV1::FailClosed,
    )])
    .expect("policy");
    let validated = ValidatedCandidateSetV1::new(input, &policy).expect("validated");

    assert!(matches!(
        validated.completeness(),
        RetrievalCompletenessDecisionV1::FailClosed { incomplete_sources }
            if incomplete_sources[0].action == IncompleteSourceActionV1::FailClosed
    ));
}

#[test]
fn omitted_expected_owner_is_typed_as_unavailable() {
    let input = GeneratedCandidateInputV1::new(vec![batch(
        RetrievalGeneratorOwnerV1::CognitiveLexical,
        RetrievalSourceCompletenessV1::Exhausted,
    )])
    .expect("input");
    let policy = RetrievalCompletenessPolicyV1::new(vec![
        row(
            RetrievalGeneratorOwnerV1::CognitiveLexical,
            IncompleteSourceActionV1::Degrade,
            IncompleteSourceActionV1::Abstain,
        ),
        row(
            RetrievalGeneratorOwnerV1::KnowledgeGraphContradiction,
            IncompleteSourceActionV1::Abstain,
            IncompleteSourceActionV1::FailClosed,
        ),
    ])
    .expect("policy");
    let validated = ValidatedCandidateSetV1::new(input, &policy).expect("validated");

    let expected = [IncompleteRetrievalSourceV1 {
        generator: RetrievalGeneratorOwnerV1::KnowledgeGraphContradiction,
        completeness: RetrievalSourceCompletenessV1::Unavailable,
        action: IncompleteSourceActionV1::FailClosed,
    }];
    assert!(matches!(
        validated.completeness(),
        RetrievalCompletenessDecisionV1::FailClosed { incomplete_sources }
            if incomplete_sources.as_slice() == expected
    ));
}

#[test]
fn omitted_optional_owner_is_explicit_degradation() {
    let input = GeneratedCandidateInputV1::new(vec![batch(
        RetrievalGeneratorOwnerV1::CognitiveLexical,
        RetrievalSourceCompletenessV1::Exhausted,
    )])
    .expect("input");
    let policy = RetrievalCompletenessPolicyV1::new(vec![
        row(
            RetrievalGeneratorOwnerV1::CognitiveLexical,
            IncompleteSourceActionV1::Degrade,
            IncompleteSourceActionV1::Abstain,
        ),
        row(
            RetrievalGeneratorOwnerV1::CognitiveTemporal,
            IncompleteSourceActionV1::Degrade,
            IncompleteSourceActionV1::Degrade,
        ),
    ])
    .expect("policy");
    let validated = ValidatedCandidateSetV1::new(input, &policy).expect("validated");

    assert!(matches!(
        validated.completeness(),
        RetrievalCompletenessDecisionV1::Degraded { incomplete_sources }
            if incomplete_sources.len() == 1
                && incomplete_sources[0].generator
                    == RetrievalGeneratorOwnerV1::CognitiveTemporal
                && incomplete_sources[0].completeness
                    == RetrievalSourceCompletenessV1::Unavailable
    ));
}

#[test]
fn missing_owner_policy_is_rejected() {
    let input = GeneratedCandidateInputV1::new(vec![batch(
        RetrievalGeneratorOwnerV1::CognitiveEntity,
        RetrievalSourceCompletenessV1::Exhausted,
    )])
    .expect("input");
    let policy = RetrievalCompletenessPolicyV1::new(vec![row(
        RetrievalGeneratorOwnerV1::CognitiveLexical,
        IncompleteSourceActionV1::Degrade,
        IncompleteSourceActionV1::Abstain,
    )])
    .expect("policy");

    assert_eq!(
        ValidatedCandidateSetV1::new(input, &policy),
        Err(ProductRecallErrorV1::MissingCompletenessPolicy(
            RetrievalGeneratorOwnerV1::CognitiveEntity
        ))
    );
}

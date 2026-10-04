use super::*;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;

use crate::EngramDynamicsPolicyV1;
use crate::EngramNodeV1;
use crate::EngramPopulationV1;
use crate::EngramSnapshotV1;
use crate::EngramSupportV1;
use crate::GeneratedCandidateInputV1;
use crate::RetrievalChannelCandidateV1;
use crate::RetrievalChannelV1;
use crate::RetrievalChannelWeightV1;
use crate::RetrievalGeneratorBatchV1;
use crate::RetrievalGeneratorOwnerV1;
use crate::RetrievalGeneratorReceiptV1;
use crate::compile_cue;
use crate::recall_generated_with_engram;

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
        scope_id: id("scope:assignment"),
        purpose_id: id("purpose:assignment"),
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
    .expect("snapshot key")
}

fn cue() -> MemoryCueV1 {
    compile_cue(
        id("cue:assignment"),
        digest("objective"),
        digest("approved-context"),
        digest("request"),
        snapshot_key(),
        digest("cue-profile"),
    )
    .expect("cue")
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

fn candidate(number: u64, channel: RetrievalChannelV1, rank: u32) -> RetrievalChannelCandidateV1 {
    RetrievalChannelCandidateV1 {
        record: record(number),
        channel,
        channel_rank: rank,
        normalized_score: FixedQ32::ONE,
        ood: ProbabilityQ32::ZERO,
        support_digest: digest(&format!("support:{number}:{channel:?}")),
        contradiction_group_digest: None,
        generation_vector_digest: cue().snapshot_key.vector_digest,
    }
}

fn batch(
    owner: RetrievalGeneratorOwnerV1,
    candidates: Vec<RetrievalChannelCandidateV1>,
    completeness: RetrievalSourceCompletenessV1,
) -> RetrievalGeneratorBatchV1 {
    let receipt = RetrievalGeneratorReceiptV1::new(
        owner,
        cue().snapshot_key.vector_digest,
        digest(&format!("owner-generation:{owner:?}")),
        u32::try_from(candidates.len()).unwrap_or(u32::MAX),
        completeness,
    )
    .expect("generator receipt");
    RetrievalGeneratorBatchV1 {
        receipt,
        candidates,
    }
}

fn policy() -> RetrievalPolicyV1 {
    RetrievalPolicyV1 {
        policy_id: id("policy:assignment"),
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
        ],
        maximum_results: 2,
        minimum_total_score: FixedQ32::ZERO,
        maximum_ood: ProbabilityQ32::ONE,
        minimum_distinct_channels: 1,
        abstain_on_contradiction: true,
    }
}

fn engram() -> EngramSnapshotV1 {
    let cue = cue();
    EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("engram-generation"),
        vec![
            EngramNodeV1 {
                node_id: id("node:1"),
                population: EngramPopulationV1::SemanticConcept,
                support: vec![EngramSupportV1 {
                    record_id: id("memory:1"),
                    record_revision: revision(1),
                }],
                threshold: FixedQ32::ZERO,
                confidence: ProbabilityQ32::ONE,
                generation_vector_digest: cue.snapshot_key.vector_digest,
            },
            EngramNodeV1 {
                node_id: id("node:2"),
                population: EngramPopulationV1::EpisodicBinding,
                support: vec![EngramSupportV1 {
                    record_id: id("memory:2"),
                    record_revision: revision(1),
                }],
                threshold: FixedQ32::ZERO,
                confidence: ProbabilityQ32::ONE,
                generation_vector_digest: cue.snapshot_key.vector_digest,
            },
        ],
        Vec::new(),
    )
    .expect("engram")
}

fn recalled(
    completeness: RetrievalSourceCompletenessV1,
) -> (
    MemoryCueV1,
    RetrievalPolicyV1,
    GeneratedCandidateInputV1,
    GeneratedRecallV1,
) {
    let cue = cue();
    let policy = policy();
    let input = GeneratedCandidateInputV1::new(vec![
        batch(
            RetrievalGeneratorOwnerV1::CognitiveLexical,
            vec![
                candidate(1, RetrievalChannelV1::Lexical, 1),
                candidate(2, RetrievalChannelV1::Lexical, 2),
            ],
            completeness,
        ),
        batch(
            RetrievalGeneratorOwnerV1::CognitiveEntity,
            vec![
                candidate(1, RetrievalChannelV1::Entity, 1),
                candidate(2, RetrievalChannelV1::Entity, 2),
            ],
            RetrievalSourceCompletenessV1::Exhausted,
        ),
    ])
    .expect("input");
    let dynamics = EngramDynamicsPolicyV1::product_default().expect("dynamics");
    let recall =
        recall_generated_with_engram(&cue, &policy, &input, &engram(), &dynamics).expect("recall");
    (cue, policy, input, recall)
}

#[test]
fn exhaustive_generators_produce_causal_eligible_assignment() {
    let (cue, policy, input, recall) = recalled(RetrievalSourceCompletenessV1::Exhausted);
    let observation =
        observe_retrieval_assignment(&cue, &policy, &input, &recall).expect("assignment");
    assert!(observation.causal_eligible());
    assert_eq!(observation.enumerated_candidates.len(), 2);
    assert_eq!(observation.legal_candidates.len(), 2);
    assert_eq!(observation.selected_candidates.len(), 2);
    assert_eq!(observation.assignment_propensity, ProbabilityQ32::ONE);
    observation.validate().expect("valid assignment");
}

#[test]
fn source_limit_is_bound_and_blocks_complete_candidate_claim() {
    let (cue, policy, input, recall) = recalled(RetrievalSourceCompletenessV1::LimitReached);
    let observation =
        observe_retrieval_assignment(&cue, &policy, &input, &recall).expect("assignment");
    assert_eq!(
        observation.completeness,
        RetrievalAssignmentCompletenessV1::GeneratorRelativeIncomplete
    );
    assert!(!observation.causal_eligible());
}

#[test]
fn policy_channel_limit_is_recorded_separately_from_source_completeness() {
    let cue = cue();
    let mut policy = policy();
    policy.channel_weights[0].maximum_candidates = 1;
    let input = GeneratedCandidateInputV1::new(vec![
        batch(
            RetrievalGeneratorOwnerV1::CognitiveLexical,
            vec![
                candidate(1, RetrievalChannelV1::Lexical, 1),
                candidate(2, RetrievalChannelV1::Lexical, 2),
            ],
            RetrievalSourceCompletenessV1::Exhausted,
        ),
        batch(
            RetrievalGeneratorOwnerV1::CognitiveEntity,
            vec![candidate(1, RetrievalChannelV1::Entity, 1)],
            RetrievalSourceCompletenessV1::Exhausted,
        ),
    ])
    .expect("input");
    let recall = recall_generated_with_engram(
        &cue,
        &policy,
        &input,
        &engram(),
        &EngramDynamicsPolicyV1::product_default().expect("dynamics"),
    )
    .expect("recall");
    let observation =
        observe_retrieval_assignment(&cue, &policy, &input, &recall).expect("assignment");
    assert!(observation.causal_eligible());
    assert_eq!(observation.omitted_by_policy_limits, 1);
    assert_eq!(observation.enumerated_candidates.len(), 2);
    assert_eq!(observation.legal_candidates.len(), 1);
}

#[test]
fn assignment_digest_detects_selected_set_tampering() {
    let (cue, policy, input, recall) = recalled(RetrievalSourceCompletenessV1::Exhausted);
    let mut observation =
        observe_retrieval_assignment(&cue, &policy, &input, &recall).expect("assignment");
    observation.selected_candidates.clear();
    assert_eq!(
        observation.validate(),
        Err(AssignmentErrorV1::DigestMismatch)
    );
}

#[test]
fn rehashed_packet_cannot_select_outside_declared_engram_support() {
    let (cue, policy, input, mut recall) = recalled(RetrievalSourceCompletenessV1::Exhausted);
    let engram = recall.packet.engram.as_mut().expect("engram");
    engram.selected_support.clear();
    engram.coverage = ProbabilityQ32::ZERO;
    engram.receipt_digest = engram.compute_receipt_digest();
    recall.packet.packet_digest = recall.packet.compute_packet_digest();
    recall.receipt_digest = recall.compute_receipt_digest();
    assert!(recall.validate().is_err());
    assert!(observe_retrieval_assignment(&cue, &policy, &input, &recall).is_err());
}

#[test]
fn rehashed_assignment_rejects_zero_candidate_identity() {
    let (cue, policy, input, recall) = recalled(RetrievalSourceCompletenessV1::Exhausted);
    let mut observed =
        observe_retrieval_assignment(&cue, &policy, &input, &recall).expect("assignment");
    for identities in [
        &mut observed.enumerated_candidates,
        &mut observed.legal_candidates,
        &mut observed.selected_candidates,
    ] {
        identities[0].record_digest = Digest32::ZERO;
    }
    observed.observation_digest = observed.compute_observation_digest();
    assert_eq!(
        observed.validate(),
        Err(AssignmentErrorV1::EmptyDigest("assignment_candidate"))
    );
}

#[test]
fn rehashed_assignment_rejects_impossible_omission_count() {
    let (cue, policy, input, recall) = recalled(RetrievalSourceCompletenessV1::Exhausted);
    let mut observed =
        observe_retrieval_assignment(&cue, &policy, &input, &recall).expect("assignment");
    observed.omitted_by_policy_limits =
        u32::try_from(crate::MAX_GENERATION_BOUND_CANDIDATES + 1).expect("bounded fixture");
    observed.observation_digest = observed.compute_observation_digest();
    assert!(observed.validate().is_err());
}

fn maximum_assignment() -> RetrievalAssignmentObservationV1 {
    let cue = cue();
    let mut policy = policy();
    policy.channel_weights = vec![RetrievalChannelWeightV1 {
        channel: RetrievalChannelV1::Lexical,
        weight: FixedQ32::ONE,
        maximum_candidates: u32::try_from(crate::MAX_GENERATION_BOUND_CANDIDATES)
            .expect("bounded candidate limit"),
    }];
    policy.minimum_distinct_channels = 1;
    policy.maximum_results =
        u32::try_from(crate::MAX_GENERATION_BOUND_RESULTS).expect("bounded result limit");
    let candidates = (0..crate::MAX_GENERATION_BOUND_CANDIDATES)
        .map(|index| {
            candidate(
                u64::try_from(index).expect("bounded identity"),
                RetrievalChannelV1::Lexical,
                u32::try_from(index + 1).expect("bounded rank"),
            )
        })
        .collect();
    let input = GeneratedCandidateInputV1::new(vec![batch(
        RetrievalGeneratorOwnerV1::CognitiveLexical,
        candidates,
        RetrievalSourceCompletenessV1::Exhausted,
    )])
    .expect("bounded owner input");
    let recall = crate::recall_generated(&cue, &policy, &input).expect("bounded recall");
    observe_retrieval_assignment(&cue, &policy, &input, &recall).expect("bounded assignment")
}

#[test]
fn assignment_validation_accepts_exact_candidate_and_result_limits() {
    let observation = maximum_assignment();
    assert_eq!(observation.validate(), Ok(()));
    assert_eq!(
        (
            observation.enumerated_candidates.len(),
            observation.legal_candidates.len(),
            observation.selected_candidates.len(),
            observation.omitted_by_policy_limits,
            observation.authority,
        ),
        (
            crate::MAX_GENERATION_BOUND_CANDIDATES,
            crate::MAX_GENERATION_BOUND_CANDIDATES,
            crate::MAX_GENERATION_BOUND_RESULTS,
            0,
            AuthorityPosture::DENY_ALL,
        ),
    );
}

#[test]
fn assignment_validation_rejects_rehashed_enumeration_above_limit() {
    let mut observation = maximum_assignment();
    observation
        .enumerated_candidates
        .push(RetrievalCandidateIdentityV1 {
            record_id: id("memory:outside-limit"),
            record_revision: revision(1),
            record_digest: digest("outside-limit"),
        });
    observation.enumerated_candidates.sort();
    observation.observation_digest = observation.compute_observation_digest();
    assert_eq!(
        observation.validate(),
        Err(AssignmentErrorV1::InvalidRecall(
            "assignment candidate limits exceeded".to_string()
        )),
    );
}

#[test]
fn assignment_validation_rejects_rehashed_selection_above_limit() {
    let mut observation = maximum_assignment();
    observation.selected_candidates =
        observation.legal_candidates[..crate::MAX_GENERATION_BOUND_RESULTS + 1].to_vec();
    observation.observation_digest = observation.compute_observation_digest();
    assert_eq!(
        observation.validate(),
        Err(AssignmentErrorV1::InvalidRecall(
            "assignment candidate limits exceeded".to_string()
        )),
    );
}

#[test]
fn assignment_validation_preserves_real_empty_support_abstention() {
    let cue = cue();
    let policy = policy();
    let input = GeneratedCandidateInputV1::new(vec![
        batch(
            RetrievalGeneratorOwnerV1::CognitiveLexical,
            Vec::new(),
            RetrievalSourceCompletenessV1::Exhausted,
        ),
        batch(
            RetrievalGeneratorOwnerV1::CognitiveEntity,
            Vec::new(),
            RetrievalSourceCompletenessV1::Exhausted,
        ),
    ])
    .expect("exhausted empty owner input");
    let recall = recall_generated_with_engram(
        &cue,
        &policy,
        &input,
        &engram(),
        &EngramDynamicsPolicyV1::product_default().expect("dynamics"),
    )
    .expect("actual empty-support recall");
    assert_eq!(recall.validate(), Ok(()));
    assert_eq!(
        recall.packet.disposition,
        crate::RecallDispositionV1::Abstained(crate::RecallAbstentionReasonV1::NoCandidate),
    );
    assert!(recall.packet.selections.is_empty());
    assert!(
        recall
            .packet
            .engram
            .as_ref()
            .expect("engram")
            .selected_support
            .is_empty()
    );
    let observed = observe_retrieval_assignment(&cue, &policy, &input, &recall)
        .expect("real abstention remains observable");
    assert_eq!(observed.validate(), Ok(()));
    assert!(observed.enumerated_candidates.is_empty());
    assert!(observed.legal_candidates.is_empty());
    assert!(observed.selected_candidates.is_empty());
    assert_eq!(observed.authority, AuthorityPosture::DENY_ALL);
}

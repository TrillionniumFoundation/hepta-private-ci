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
fn recomputed_recall_cannot_misattribute_selection_evidence() {
    let (cue, policy, input, mut recall) = recalled(RetrievalSourceCompletenessV1::Exhausted);
    recall.packet.selections[0].support_digests = vec![digest("unobserved-support")];
    recall.packet.packet_digest = recall.packet.compute_packet_digest();
    recall.receipt_digest = recall.compute_receipt_digest();
    recall
        .validate()
        .expect("self-consistent digest is not provenance");
    assert_eq!(
        observe_retrieval_assignment(&cue, &policy, &input, &recall),
        Err(AssignmentErrorV1::SelectedEvidenceMismatch)
    );
}

#[test]
fn recomputed_recall_cannot_hide_omitted_candidate_count() {
    let (cue, policy, input, mut recall) = recalled(RetrievalSourceCompletenessV1::Exhausted);
    recall.packet.engram = None;
    recall.packet.omitted_count = 1;
    recall.packet.packet_digest = recall.packet.compute_packet_digest();
    recall.receipt_digest = recall.compute_receipt_digest();
    recall.validate().expect("self-consistent recall");
    assert_eq!(
        observe_retrieval_assignment(&cue, &policy, &input, &recall),
        Err(AssignmentErrorV1::RecallUnionMismatch)
    );
}

#[test]
fn assignment_candidate_bounds_and_zero_digests_fail_after_rehash() {
    let (cue, policy, input, recall) = recalled(RetrievalSourceCompletenessV1::Exhausted);
    let original =
        observe_retrieval_assignment(&cue, &policy, &input, &recall).expect("assignment");
    let mut invalid = original.clone();
    invalid.enumerated_candidates[0].record_digest = Digest32::ZERO;
    invalid.observation_digest = invalid.compute_observation_digest();
    assert_eq!(
        invalid.validate(),
        Err(AssignmentErrorV1::EmptyDigest("assignment_candidate"))
    );
    let mut invalid = original;
    invalid.omitted_by_policy_limits = 513;
    invalid.observation_digest = invalid.compute_observation_digest();
    assert_eq!(
        invalid.validate(),
        Err(AssignmentErrorV1::CandidateLimitExceeded)
    );
}

#[test]
fn plain_assignment_replays_deterministic_selection_after_rehash() {
    let (cue, mut policy, input, _) = recalled(RetrievalSourceCompletenessV1::Exhausted);
    policy.maximum_results = 1;
    let full = crate::build_candidate_union_from_generated(&cue, &policy, &input).expect("union");
    let mut recall = crate::recall_generated(&cue, &policy, &input).expect("recall");
    observe_retrieval_assignment(&cue, &policy, &input, &recall).expect("valid plain assignment");
    let other = &full.union.entries[1];
    recall.packet.selections[0] = crate::RecallSelectionV1 {
        record_id: other.record.record_id.clone(),
        record_revision: other.record.revision,
        record_digest: other.record.record_digest(),
        weighted_score: other.weighted_score,
        maximum_ood: other.maximum_ood,
        channels: other.channels.clone(),
        support_digests: other.support_digests.clone(),
        contradiction_group_digests: other.contradiction_group_digests.clone(),
    };
    recall.packet.packet_digest = recall.packet.compute_packet_digest();
    recall.receipt_digest = recall.compute_receipt_digest();
    recall.validate().expect("legal but not assigned candidate");
    assert_eq!(
        observe_retrieval_assignment(&cue, &policy, &input, &recall),
        Err(AssignmentErrorV1::RecallUnionMismatch)
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
fn rehashed_hnmf_cannot_replace_the_deterministic_winner() {
    let (cue, mut policy, input, complete) = recalled(RetrievalSourceCompletenessV1::Exhausted);
    policy.maximum_results = 1;
    let mut recall = recall_generated_with_engram(
        &cue,
        &policy,
        &input,
        &engram(),
        &EngramDynamicsPolicyV1::product_default().expect("dynamics"),
    )
    .expect("recall");
    recall.packet.selections[0] = complete.packet.selections[1].clone();
    recall.packet.packet_digest = recall.packet.compute_packet_digest();
    recall.receipt_digest = recall.compute_receipt_digest();
    recall
        .validate()
        .expect("structurally valid lower-ranked choice");
    assert_eq!(
        observe_retrieval_assignment(&cue, &policy, &input, &recall),
        Err(AssignmentErrorV1::RecallUnionMismatch)
    );
}

#[test]
fn rehashed_hnmf_cannot_forge_abstention() {
    let (cue, policy, input, mut recall) = recalled(RetrievalSourceCompletenessV1::Exhausted);
    recall.packet.disposition =
        RecallDispositionV1::Abstained(crate::RecallAbstentionReasonV1::NoCandidate);
    recall.packet.selections.clear();
    recall.packet.omitted_count = 0;
    recall.packet.packet_digest = recall.packet.compute_packet_digest();
    recall.receipt_digest = recall.compute_receipt_digest();
    recall.validate().expect("structurally valid abstention");
    assert_eq!(
        observe_retrieval_assignment(&cue, &policy, &input, &recall),
        Err(AssignmentErrorV1::RecallUnionMismatch)
    );
}

#[test]
fn rehashed_hnmf_cannot_bypass_ood() {
    let (cue, mut policy, input, _) = recalled(RetrievalSourceCompletenessV1::Exhausted);
    policy.maximum_ood = ProbabilityQ32::ZERO;
    let mut batches = input.batches;
    for batch in &mut batches {
        for candidate in &mut batch.candidates {
            candidate.ood = ProbabilityQ32::ONE;
        }
    }
    let input = GeneratedCandidateInputV1::new(batches).expect("OOD input");
    let mut recall = recall_generated_with_engram(
        &cue,
        &policy,
        &input,
        &engram(),
        &EngramDynamicsPolicyV1::product_default().expect("dynamics"),
    )
    .expect("OOD recall");
    observe_retrieval_assignment(&cue, &policy, &input, &recall).expect("valid OOD abstention");
    recall.packet.disposition = RecallDispositionV1::Recalled;
    let union = crate::build_candidate_union_from_generated(&cue, &policy, &input).expect("union");
    recall.packet.selections = crate::engram::select_engram_candidates(
        &union.union,
        &policy,
        recall.packet.engram.as_ref().expect("receipt"),
    )
    .1;
    recall.packet.packet_digest = recall.packet.compute_packet_digest();
    recall.receipt_digest = recall.compute_receipt_digest();
    recall.validate().expect("structurally valid OOD selection");
    assert_eq!(
        observe_retrieval_assignment(&cue, &policy, &input, &recall),
        Err(AssignmentErrorV1::RecallUnionMismatch)
    );
}

#[test]
fn hnmf_assignment_preserves_both_owner_dynamics_contradiction_postures() {
    let (cue, mut policy, input, _) = recalled(RetrievalSourceCompletenessV1::Exhausted);
    policy.abstain_on_contradiction = false;
    let mut batches = input.batches;
    for batch in &mut batches {
        for candidate in &mut batch.candidates {
            candidate.contradiction_group_digest = Some(
                crate::ContradictionEvidenceV2::new(
                    digest("shared-contradiction"),
                    cue.snapshot_key.vector_digest,
                    if candidate.record.record_id == id("memory:1") {
                        crate::PropositionPolarityV2::Affirmed
                    } else {
                        crate::PropositionPolarityV2::Denied
                    },
                )
                .expect("same proposition and generation with opposite polarities"),
            );
        }
    }
    let input = GeneratedCandidateInputV1::new(batches).expect("contradictory input");
    for force_abstention in [true, false] {
        let mut dynamics = EngramDynamicsPolicyV1::product_default().expect("dynamics");
        dynamics.contradiction_forces_abstention = force_abstention;
        let recall = recall_generated_with_engram(&cue, &policy, &input, &engram(), &dynamics)
            .expect("owner-generated recall");
        observe_retrieval_assignment(&cue, &policy, &input, &recall)
            .expect("both actual owner policies are accepted");
        let expected = if force_abstention {
            RecallDispositionV1::Abstained(crate::RecallAbstentionReasonV1::ContradictoryEvidence)
        } else {
            RecallDispositionV1::Recalled
        };
        assert_eq!(recall.packet.disposition, expected);
    }
}

#[test]
fn assignment_verifies_admitted_dynamics_without_losing_rejected_input_accounting() {
    let cue = cue();
    let mut policy = policy();
    policy.minimum_total_score = FixedQ32::from_raw(FixedQ32::ONE.raw() / 2);
    policy.maximum_ood = ProbabilityQ32::ZERO;
    let mut rejected = candidate(2, RetrievalChannelV1::Entity, 1);
    rejected.normalized_score = FixedQ32::from_raw(FixedQ32::ONE.raw() / 4);
    rejected.ood = ProbabilityQ32::ONE;
    let input = GeneratedCandidateInputV1::new(vec![
        batch(
            RetrievalGeneratorOwnerV1::CognitiveLexical,
            vec![candidate(1, RetrievalChannelV1::Lexical, 1)],
            RetrievalSourceCompletenessV1::Exhausted,
        ),
        batch(
            RetrievalGeneratorOwnerV1::CognitiveEntity,
            vec![rejected],
            RetrievalSourceCompletenessV1::Exhausted,
        ),
    ])
    .expect("complete original enumeration");
    let dynamics = EngramDynamicsPolicyV1::product_default().expect("dynamics");
    let recalls = [
        crate::recall_generated(&cue, &policy, &input).expect("plain admitted recall"),
        recall_generated_with_engram(&cue, &policy, &input, &engram(), &dynamics)
            .expect("admitted engram recall"),
    ];
    for recall in recalls {
        assert_eq!(recall.packet.disposition, RecallDispositionV1::Recalled);
        assert_eq!(recall.packet.distinct_channels, 1);
        assert_eq!(recall.packet.omitted_count, 1);
        let observed = observe_retrieval_assignment(&cue, &policy, &input, &recall)
            .expect("same deterministic assignment despite rejected OOD input");
        assert_eq!(observed.enumerated_candidates.len(), 2);
        assert_eq!(observed.selected_candidates.len(), 1);
        assert_eq!(observed.selected_candidates[0].record_id, id("memory:1"));
        if let Some(engram) = &recall.packet.engram {
            assert_eq!(engram.resources.candidate_records, 2);
            assert_eq!(engram.selected_support.len(), 1);
        }
    }
}

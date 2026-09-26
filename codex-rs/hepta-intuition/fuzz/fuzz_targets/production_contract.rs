#![no_main]

use codex_hepta_intuition::AssignmentCommitmentV2;
use codex_hepta_intuition::AssignmentModeV1;
use codex_hepta_intuition::CalibratedActionCandidateV1;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibrationArtifactV1;
use codex_hepta_intuition::CandidateSetCompletenessBindingV1;
use codex_hepta_intuition::OodArtifactV1;
use codex_hepta_intuition::PolicyGeneration;
use codex_hepta_intuition::RiskClass;
use codex_hepta_intuition::ScoringCommitmentV2;
use codex_hepta_intuition::canonical_assignment_commitment_digest_v2;
use codex_hepta_intuition::canonical_assignment_distribution_digest_v2;
use codex_hepta_intuition::canonical_candidate_identity_digest_v2;
use codex_hepta_intuition::canonical_candidate_order_digest_v1;
use codex_hepta_intuition::canonical_candidate_set_digest_v1;
use codex_hepta_intuition::canonical_scored_outputs_digest_v2;
use codex_hepta_intuition::canonical_scoring_commitment_digest_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use libfuzzer_sys::fuzz_target;

fn digest(label: &[u8]) -> Digest32 {
    Digest32::of_bytes(label)
}

fn id(value: String) -> StableId {
    StableId::new(value).expect("generated stable id")
}

fuzz_target!(|data: &[u8]| {
    if data.is_empty() {
        return;
    }
    let count = usize::from(data[0] % 16) + 1;
    let mut candidates = Vec::with_capacity(count);
    for index in 0..count {
        let byte = data.get(index + 1).copied().unwrap_or(index as u8);
        let probability = ProbabilityQ32::from_raw(
            u64::from(byte) * ProbabilityQ32::ONE.raw() / u64::from(u8::MAX),
        )
        .expect("bounded probability");
        candidates.push(CalibratedActionCandidateV1 {
            candidate_id: id(format!("candidate:{index}:{byte}")),
            legal: byte & 1 == 0,
            hard_veto: byte & 2 != 0,
            utility: FixedQ32::from_raw(i64::from(byte) - 128),
            calibrated_confidence: probability,
            ood_score: ProbabilityQ32::from_raw(
                ProbabilityQ32::ONE.raw().saturating_sub(probability.raw()),
            )
            .expect("bounded inverse probability"),
            assignment_probability: probability,
            support_digest: digest(&[byte, index as u8]),
        });
    }

    let Ok(candidate_set_digest) = canonical_candidate_set_digest_v1(&candidates) else {
        return;
    };
    let Ok(canonical_order_digest) = canonical_candidate_order_digest_v1(&candidates) else {
        return;
    };
    let request = CalibratedDecisionRequestV1 {
        decision_id: id("decision:fuzz".to_string()),
        objective_digest: digest(b"objective"),
        objective_class_digest: digest(b"objective-class"),
        state_digest: digest(b"state"),
        policy_digest: digest(b"policy"),
        policy_generation: 1,
        sequence: 1,
        minimum_confidence: ProbabilityQ32::ZERO,
        maximum_ece_ppm: 1_000_000,
        maximum_ood_false_acceptance_ppm: 1_000_000,
        risk_class: RiskClass::Low,
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: digest(b"completeness"),
            generator_digest: digest(b"generator"),
            grammar_digest: digest(b"grammar"),
            hard_filter_digest: digest(b"hard-filter"),
            truncation_digest: digest(b"truncation"),
            candidate_set_digest,
            canonical_order_digest,
            candidate_count: candidates.len() as u32,
            omitted_count_bound: 0,
        },
        calibration: CalibrationArtifactV1 {
            artifact_digest: digest(b"calibration"),
            policy_digest: digest(b"policy"),
            objective_class_digest: digest(b"objective-class"),
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 1,
            measured_ece_ppm: 0,
            subgroup_audit_digest: digest(b"subgroup"),
        },
        ood: OodArtifactV1 {
            artifact_digest: digest(b"ood"),
            policy_digest: digest(b"policy"),
            detector_digest: digest(b"detector"),
            support_digest: digest(b"ood-support"),
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 1,
            maximum_in_domain_score: ProbabilityQ32::ONE,
            measured_false_acceptance_ppm: 0,
        },
        assignment: AssignmentModeV1::Deterministic,
        candidates,
    };

    let Ok(identity) = canonical_candidate_identity_digest_v2(&request.candidates) else {
        return;
    };
    let Ok(scored) = canonical_scored_outputs_digest_v2(&request) else {
        return;
    };
    let Ok(distribution) = canonical_assignment_distribution_digest_v2(&request) else {
        return;
    };
    let scoring = ScoringCommitmentV2 {
        model_artifact_digest: digest(b"model"),
        feature_snapshot_digest: digest(b"feature-snapshot"),
        feature_schema_digest: digest(b"feature-schema"),
        scorer_contract_digest: digest(b"scorer-contract"),
        candidate_identity_digest: identity,
        scored_outputs_digest: scored,
        policy_digest: digest(b"policy"),
        policy_generation: PolicyGeneration::new(1).expect("generation"),
    };
    let assignment = AssignmentCommitmentV2::Deterministic {
        distribution_digest: distribution,
    };
    let _ = canonical_scoring_commitment_digest_v2(&scoring);
    let _ = canonical_assignment_commitment_digest_v2(&request, &assignment);
});

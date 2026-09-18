use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::calibrated::AssignmentModeV1;
use crate::calibrated::CalibratedDecisionRequestV1;
use crate::calibrated::CalibrationArtifactV1;
use crate::calibrated::RiskClass;
use crate::calibrated::CandidateSetCompletenessBindingV1;
use crate::calibrated::OodArtifactV1;

use super::CanonicalPolicyProfileV1;
use super::LearnedScoreEvidenceV1;
use super::LearnedScorerContractV1;
use super::QualifiedError;
use super::RiskPolicyV1;

pub fn canonical_assignment_digest_v1(
    request: &CalibratedDecisionRequestV1,
    policy_profile_digest: Digest32,
    scorer_output_digest: Digest32,
) -> Result<Digest32, QualifiedError> {
    if policy_profile_digest.is_zero() {
        return Err(QualifiedError::EmptyDigest("policy profile"));
    }
    if scorer_output_digest.is_zero() {
        return Err(QualifiedError::EmptyDigest("scorer output"));
    }

    let mut bytes = b"hepta.intuition.policy-assignment.v1\0".to_vec();
    push_id(&mut bytes, &request.decision_id)?;
    for digest in [
        request.objective_digest,
        request.objective_class_digest,
        request.state_digest,
        request.policy_digest,
        request.completeness.receipt_digest,
        request.completeness.candidate_set_digest,
        policy_profile_digest,
        scorer_output_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&request.policy_generation.to_be_bytes());
    bytes.extend_from_slice(&request.sequence.to_be_bytes());
    bytes.push(risk_class_code(request.risk_class));
    push_len(&mut bytes, request.candidates.len())?;
    for candidate in &request.candidates {
        push_id(&mut bytes, &candidate.candidate_id)?;
        bytes.extend_from_slice(&candidate.assignment_probability.raw().to_be_bytes());
    }
    match &request.assignment {
        AssignmentModeV1::Deterministic => bytes.push(0),
        AssignmentModeV1::CounterBased {
            random_stream_digest,
            draw,
            abstain_probability,
        } => {
            bytes.push(1);
            bytes.extend_from_slice(random_stream_digest.as_array());
            bytes.extend_from_slice(&draw.raw().to_be_bytes());
            bytes.extend_from_slice(&abstain_probability.raw().to_be_bytes());
        }
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub fn canonical_policy_profile_digest_v1(
    profile: &CanonicalPolicyProfileV1,
) -> Result<Digest32, QualifiedError> {
    let mut bytes = b"hepta.intuition.policy-profile.v1\0".to_vec();
    for digest in [
        profile.policy_digest,
        profile.objective_class_digest,
        profile.scorer_contract_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&profile.generation.to_be_bytes());
    bytes.extend_from_slice(&profile.valid_from_sequence.to_be_bytes());
    bytes.extend_from_slice(&profile.expires_after_sequence.to_be_bytes());
    bytes.extend_from_slice(&profile.minimum_confidence.raw().to_be_bytes());
    bytes.extend_from_slice(&profile.maximum_ece_ppm.to_be_bytes());
    bytes.extend_from_slice(&profile.maximum_ood_false_acceptance_ppm.to_be_bytes());
    bytes.push(risk_policy_code(profile.risk_policy));
    bytes.push(u8::from(profile.require_zero_omissions));
    Ok(Digest32::of_bytes(&bytes))
}

#[must_use]
pub fn canonical_calibration_artifact_digest_v1(artifact: &CalibrationArtifactV1) -> Digest32 {
    let mut bytes = b"hepta.intuition.calibration-artifact.v1\0".to_vec();
    for digest in [
        artifact.policy_digest,
        artifact.objective_class_digest,
        artifact.subgroup_audit_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&artifact.generation.to_be_bytes());
    bytes.extend_from_slice(&artifact.valid_from_sequence.to_be_bytes());
    bytes.extend_from_slice(&artifact.expires_after_sequence.to_be_bytes());
    bytes.extend_from_slice(&artifact.measured_ece_ppm.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[must_use]
pub fn canonical_ood_artifact_digest_v1(artifact: &OodArtifactV1) -> Digest32 {
    let mut bytes = b"hepta.intuition.ood-artifact.v1\0".to_vec();
    for digest in [
        artifact.policy_digest,
        artifact.detector_digest,
        artifact.support_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&artifact.generation.to_be_bytes());
    bytes.extend_from_slice(&artifact.valid_from_sequence.to_be_bytes());
    bytes.extend_from_slice(&artifact.expires_after_sequence.to_be_bytes());
    bytes.extend_from_slice(&artifact.maximum_in_domain_score.raw().to_be_bytes());
    bytes.extend_from_slice(&artifact.measured_false_acceptance_ppm.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[must_use]
pub fn canonical_completeness_receipt_digest_v1(
    completeness: &CandidateSetCompletenessBindingV1,
    state_digest: Digest32,
    policy_digest: Digest32,
    generation: u64,
    sequence: u64,
) -> Digest32 {
    let mut bytes = b"hepta.intuition.completeness-receipt.v1\0".to_vec();
    for digest in [
        state_digest,
        policy_digest,
        completeness.generator_digest,
        completeness.grammar_digest,
        completeness.hard_filter_digest,
        completeness.truncation_digest,
        completeness.candidate_set_digest,
        completeness.canonical_order_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&generation.to_be_bytes());
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.extend_from_slice(&completeness.candidate_count.to_be_bytes());
    bytes.extend_from_slice(&completeness.omitted_count_bound.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[must_use]
pub fn canonical_scorer_contract_digest_v1(contract: &LearnedScorerContractV1) -> Digest32 {
    let mut bytes = b"hepta.intuition.learned-scorer-contract.v1\0".to_vec();
    for digest in [
        contract.policy_digest,
        contract.objective_class_digest,
        contract.model_artifact_digest,
        contract.feature_schema_digest,
        contract.utility_semantics_digest,
        contract.confidence_semantics_digest,
        contract.ood_semantics_digest,
        contract.calibration_artifact_digest,
        contract.ood_artifact_digest,
        contract.ood_detector_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&contract.generation.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

pub fn canonical_scorer_output_digest_v1(
    decision_id: &StableId,
    state_digest: Digest32,
    scorer_contract_digest: Digest32,
    model_artifact_digest: Digest32,
    evidence: &[LearnedScoreEvidenceV1],
) -> Result<Digest32, QualifiedError> {
    let mut bytes = b"hepta.intuition.learned-scorer-output.v1\0".to_vec();
    push_id(&mut bytes, decision_id)?;
    for digest in [
        state_digest,
        scorer_contract_digest,
        model_artifact_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_len(&mut bytes, evidence.len())?;
    for row in evidence {
        push_id(&mut bytes, &row.candidate_id)?;
        bytes.extend_from_slice(row.feature_digest.as_array());
        bytes.extend_from_slice(&row.utility.raw().to_be_bytes());
        bytes.extend_from_slice(&row.calibrated_confidence.raw().to_be_bytes());
        bytes.extend_from_slice(&row.ood_score.raw().to_be_bytes());
        bytes.extend_from_slice(row.support_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub(crate) fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), QualifiedError> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| QualifiedError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), QualifiedError> {
    let value = u32::try_from(value).map_err(|_| QualifiedError::Arithmetic)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

const fn risk_class_code(value: RiskClass) -> u8 {
    match value {
        RiskClass::Low => 0,
        RiskClass::Elevated => 1,
        RiskClass::High => 2,
    }
}

const fn risk_policy_code(value: RiskPolicyV1) -> u8 {
    match value {
        RiskPolicyV1::HighAlwaysSlowPath => 0,
        RiskPolicyV1::LowOnlyFastPath => 1,
    }
}

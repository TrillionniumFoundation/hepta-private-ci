//! Current-generation qualification profile for calibrated intuition decisions.
//!
//! This layer remains pure and authority-free. It freezes policy thresholds,
//! learned-scorer lineage and accepted calibration/OOD metadata. Cryptographic
//! authentication belongs to a consumer with a host-owned trust snapshot.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::calibrated::AssignmentModeV1;
use crate::calibrated::CalibratedDecisionRequestV1;
use crate::calibrated::CalibratedError;
use crate::calibrated::CalibratedIntuitionReceiptV1;
use crate::calibrated::RiskClass;
use crate::calibrated::canonical_calibrated_request_digest_v1;
use crate::calibrated::canonical_candidate_order_digest_v1;
use crate::calibrated::canonical_candidate_set_digest_v1;
use crate::calibrated::decide_calibrated_v2;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearnedScorerContractV1 {
    pub model_digest: Digest32,
    pub feature_schema_digest: Digest32,
    pub output_schema_digest: Digest32,
    pub score_semantics_digest: Digest32,
    pub scorer_contract_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScoringCommitmentV1 {
    pub decision_id: StableId,
    pub model_artifact_digest: Digest32,
    pub feature_schema_digest: Digest32,
    pub feature_snapshot_digest: Digest32,
    pub scorer_contract_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub scored_candidates_digest: Digest32,
    pub policy_digest: Digest32,
    pub policy_generation: u64,
    pub sequence: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CanonicalRiskRuleV1 {
    HighOnlySlowPath,
    ElevatedAndHighSlowPath,
    AlwaysSlowPath,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalPolicyProfileV1 {
    pub profile_id: StableId,
    pub policy_digest: Digest32,
    pub objective_class_digest: Digest32,
    pub generation: u64,
    pub valid_from_sequence: u64,
    pub expires_after_sequence: u64,
    pub minimum_confidence: ProbabilityQ32,
    pub maximum_ece_ppm: u32,
    pub maximum_ood_false_acceptance_ppm: u32,
    pub maximum_in_domain_score: ProbabilityQ32,
    pub risk_rule: CanonicalRiskRuleV1,
    pub scorer: LearnedScorerContractV1,
    pub calibration_dataset_digest: Digest32,
    pub ood_dataset_digest: Digest32,
    pub calibration_artifact_digest: Digest32,
    pub calibration_measured_ece_ppm: u32,
    pub calibration_subgroup_audit_digest: Digest32,
    pub ood_artifact_digest: Digest32,
    pub ood_measured_false_acceptance_ppm: u32,
    pub ood_detector_digest: Digest32,
    pub ood_support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum QualifiedCalibratedError {
    Policy(CalibratedError),
    EmptyProfileDigest(&'static str),
    EmptyScoringDigest(&'static str),
    InvalidProfileGeneration,
    InvalidProfileWindow,
    ProfileExpired,
    ProfilePolicyMismatch,
    ProfileObjectiveMismatch,
    ProfileGenerationMismatch,
    ProfileThresholdMismatch(&'static str),
    ProfileArtifactMismatch(&'static str),
    ProfileArtifactMetadataMismatch(&'static str),
    ScoringCommitmentMismatch(&'static str),
    AssignmentEvidenceRequiresCounterBased,
}

impl fmt::Display for QualifiedCalibratedError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for QualifiedCalibratedError {}

impl From<CalibratedError> for QualifiedCalibratedError {
    fn from(value: CalibratedError) -> Self {
        Self::Policy(value)
    }
}

pub fn canonical_policy_profile_digest_v1(
    profile: &CanonicalPolicyProfileV1,
) -> Result<Digest32, QualifiedCalibratedError> {
    validate_profile_shape(profile)?;
    let mut bytes = b"hepta.intuition.canonical-policy-profile.v1\0".to_vec();
    push_id(&mut bytes, &profile.profile_id)?;
    for digest in [
        profile.policy_digest,
        profile.objective_class_digest,
        profile.scorer.model_digest,
        profile.scorer.feature_schema_digest,
        profile.scorer.output_schema_digest,
        profile.scorer.score_semantics_digest,
        profile.scorer.scorer_contract_digest,
        profile.calibration_dataset_digest,
        profile.ood_dataset_digest,
        profile.calibration_artifact_digest,
        profile.calibration_subgroup_audit_digest,
        profile.ood_artifact_digest,
        profile.ood_detector_digest,
        profile.ood_support_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for value in [
        profile.generation,
        profile.valid_from_sequence,
        profile.expires_after_sequence,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes.extend_from_slice(&profile.minimum_confidence.raw().to_be_bytes());
    bytes.extend_from_slice(&profile.maximum_ece_ppm.to_be_bytes());
    bytes.extend_from_slice(&profile.maximum_ood_false_acceptance_ppm.to_be_bytes());
    bytes.extend_from_slice(&profile.maximum_in_domain_score.raw().to_be_bytes());
    bytes.extend_from_slice(&profile.calibration_measured_ece_ppm.to_be_bytes());
    bytes.extend_from_slice(&profile.ood_measured_false_acceptance_ppm.to_be_bytes());
    bytes.push(risk_rule_code(profile.risk_rule));
    Ok(Digest32::of_bytes(&bytes))
}

pub fn canonical_scored_candidates_digest_v1(
    request: &CalibratedDecisionRequestV1,
) -> Result<Digest32, QualifiedCalibratedError> {
    let mut bytes = b"hepta.intuition.scored-candidates.v1\0".to_vec();
    let count =
        u32::try_from(request.candidates.len()).map_err(|_| CalibratedError::Arithmetic)?;
    bytes.extend_from_slice(&count.to_be_bytes());
    for candidate in &request.candidates {
        push_id(&mut bytes, &candidate.candidate_id)?;
        bytes.extend_from_slice(&candidate.utility.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.calibrated_confidence.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.ood_score.raw().to_be_bytes());
        bytes.extend_from_slice(candidate.support_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub fn canonical_scoring_commitment_digest_v1(
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
    commitment: &ScoringCommitmentV1,
) -> Result<Digest32, QualifiedCalibratedError> {
    validate_profile_for_request(request, profile)?;
    validate_scoring_commitment(request, profile, commitment)?;
    let mut bytes = b"hepta.intuition.scoring-commitment.v1\0".to_vec();
    push_id(&mut bytes, &commitment.decision_id)?;
    for digest in [
        commitment.model_artifact_digest,
        commitment.feature_schema_digest,
        commitment.feature_snapshot_digest,
        commitment.scorer_contract_digest,
        commitment.candidate_set_digest,
        commitment.scored_candidates_digest,
        commitment.policy_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&commitment.policy_generation.to_be_bytes());
    bytes.extend_from_slice(&commitment.sequence.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

pub fn canonical_completeness_evidence_payload_v1(
    request: &CalibratedDecisionRequestV1,
) -> Result<Vec<u8>, QualifiedCalibratedError> {
    let candidate_set_digest = canonical_candidate_set_digest_v1(&request.candidates)?;
    let order_digest = canonical_candidate_order_digest_v1(&request.candidates)?;
    let mut bytes = b"hepta.intuition.completeness-evidence.v1\0".to_vec();
    push_id(&mut bytes, &request.decision_id)?;
    for digest in [
        request.objective_digest,
        request.objective_class_digest,
        request.state_digest,
        request.policy_digest,
        request.completeness.receipt_digest,
        request.completeness.generator_digest,
        request.completeness.grammar_digest,
        request.completeness.hard_filter_digest,
        request.completeness.truncation_digest,
        request.completeness.candidate_set_digest,
        request.completeness.canonical_order_digest,
        candidate_set_digest,
        order_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&request.policy_generation.to_be_bytes());
    bytes.extend_from_slice(&request.sequence.to_be_bytes());
    bytes.extend_from_slice(&request.completeness.candidate_count.to_be_bytes());
    bytes.extend_from_slice(&request.completeness.omitted_count_bound.to_be_bytes());
    Ok(bytes)
}

pub fn canonical_profile_qualification_evidence_payload_v1(
    profile: &CanonicalPolicyProfileV1,
) -> Result<Vec<u8>, QualifiedCalibratedError> {
    let profile_digest = canonical_policy_profile_digest_v1(profile)?;
    let mut bytes = b"hepta.intuition.profile-qualification-evidence.v1\0".to_vec();
    bytes.extend_from_slice(profile_digest.as_array());
    Ok(bytes)
}

pub fn canonical_scoring_evidence_payload_v1(
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
    commitment: &ScoringCommitmentV1,
) -> Result<Vec<u8>, QualifiedCalibratedError> {
    let profile_digest = canonical_policy_profile_digest_v1(profile)?;
    let scoring_digest = canonical_scoring_commitment_digest_v1(request, profile, commitment)?;
    let mut bytes = b"hepta.intuition.scoring-evidence.v1\0".to_vec();
    bytes.extend_from_slice(profile_digest.as_array());
    bytes.extend_from_slice(scoring_digest.as_array());
    Ok(bytes)
}

pub fn canonical_decision_request_evidence_payload_v1(
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
    commitment: &ScoringCommitmentV1,
) -> Result<Vec<u8>, QualifiedCalibratedError> {
    let request_digest = canonical_calibrated_request_digest_v1(request)?;
    let profile_digest = canonical_policy_profile_digest_v1(profile)?;
    let scoring_digest = canonical_scoring_commitment_digest_v1(request, profile, commitment)?;
    let mut bytes = b"hepta.intuition.decision-request-evidence.v1\0".to_vec();
    bytes.extend_from_slice(request_digest.as_array());
    bytes.extend_from_slice(profile_digest.as_array());
    bytes.extend_from_slice(scoring_digest.as_array());
    Ok(bytes)
}

pub fn canonical_assignment_evidence_payload_v1(
    request: &CalibratedDecisionRequestV1,
) -> Result<Vec<u8>, QualifiedCalibratedError> {
    let AssignmentModeV1::CounterBased {
        random_stream_digest,
        draw,
        abstain_probability,
    } = &request.assignment
    else {
        return Err(QualifiedCalibratedError::AssignmentEvidenceRequiresCounterBased);
    };
    let mut bytes = b"hepta.intuition.assignment-evidence.v1\0".to_vec();
    push_id(&mut bytes, &request.decision_id)?;
    for digest in [
        request.state_digest,
        request.policy_digest,
        request.completeness.candidate_set_digest,
        *random_stream_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&request.policy_generation.to_be_bytes());
    bytes.extend_from_slice(&request.sequence.to_be_bytes());
    bytes.extend_from_slice(&draw.raw().to_be_bytes());
    bytes.extend_from_slice(&abstain_probability.raw().to_be_bytes());
    Ok(bytes)
}

pub fn canonical_qualification_evidence_payload_v1(
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
) -> Result<Vec<u8>, QualifiedCalibratedError> {
    validate_profile_for_request(request, profile)?;
    let request_digest = canonical_calibrated_request_digest_v1(request)?;
    let profile_digest = canonical_policy_profile_digest_v1(profile)?;
    let mut bytes = b"hepta.intuition.qualification-evidence.v1\0".to_vec();
    bytes.extend_from_slice(request_digest.as_array());
    bytes.extend_from_slice(profile_digest.as_array());
    bytes.extend_from_slice(request.completeness.receipt_digest.as_array());
    bytes.extend_from_slice(request.calibration.artifact_digest.as_array());
    bytes.extend_from_slice(request.ood.artifact_digest.as_array());
    Ok(bytes)
}

pub fn decide_calibrated_v3(
    request: CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
) -> Result<CalibratedIntuitionReceiptV1, QualifiedCalibratedError> {
    validate_profile_for_request(&request, profile)?;
    let original_request_digest = canonical_calibrated_request_digest_v1(&request)?;
    let profile_digest = canonical_policy_profile_digest_v1(profile)?;

    let force_slow_path = risk_requires_slow_path(profile.risk_rule, request.risk_class);
    let mut effective = request;
    if force_slow_path && effective.risk_class != RiskClass::High {
        effective.risk_class = RiskClass::High;
    }
    let mut receipt = decide_calibrated_v2(effective)?;
    let mut bytes = b"hepta.intuition.calibrated-decision.v3\0".to_vec();
    bytes.extend_from_slice(original_request_digest.as_array());
    bytes.extend_from_slice(profile_digest.as_array());
    bytes.extend_from_slice(receipt.receipt_digest.as_array());
    bytes.push(u8::from(force_slow_path));
    receipt.receipt_digest = Digest32::of_bytes(&bytes);
    Ok(receipt)
}

fn validate_scoring_commitment(
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
    commitment: &ScoringCommitmentV1,
) -> Result<(), QualifiedCalibratedError> {
    for (name, digest) in [
        ("model artifact", commitment.model_artifact_digest),
        ("feature schema", commitment.feature_schema_digest),
        ("feature snapshot", commitment.feature_snapshot_digest),
        ("scorer contract", commitment.scorer_contract_digest),
        ("candidate set", commitment.candidate_set_digest),
        ("scored candidates", commitment.scored_candidates_digest),
        ("policy", commitment.policy_digest),
    ] {
        if digest.is_zero() {
            return Err(QualifiedCalibratedError::EmptyScoringDigest(name));
        }
    }
    if commitment.decision_id != request.decision_id {
        return Err(QualifiedCalibratedError::ScoringCommitmentMismatch(
            "decision",
        ));
    }
    if commitment.model_artifact_digest != profile.scorer.model_digest {
        return Err(QualifiedCalibratedError::ScoringCommitmentMismatch("model"));
    }
    if commitment.feature_schema_digest != profile.scorer.feature_schema_digest {
        return Err(QualifiedCalibratedError::ScoringCommitmentMismatch(
            "feature schema",
        ));
    }
    if commitment.scorer_contract_digest != profile.scorer.scorer_contract_digest {
        return Err(QualifiedCalibratedError::ScoringCommitmentMismatch(
            "scorer contract",
        ));
    }
    if commitment.candidate_set_digest != request.completeness.candidate_set_digest {
        return Err(QualifiedCalibratedError::ScoringCommitmentMismatch(
            "candidate set",
        ));
    }
    if commitment.scored_candidates_digest != canonical_scored_candidates_digest_v1(request)? {
        return Err(QualifiedCalibratedError::ScoringCommitmentMismatch("scores"));
    }
    if commitment.policy_digest != request.policy_digest
        || commitment.policy_digest != profile.policy_digest
    {
        return Err(QualifiedCalibratedError::ScoringCommitmentMismatch("policy"));
    }
    if commitment.policy_generation != request.policy_generation
        || commitment.policy_generation != profile.generation
    {
        return Err(QualifiedCalibratedError::ScoringCommitmentMismatch(
            "generation",
        ));
    }
    if commitment.sequence != request.sequence {
        return Err(QualifiedCalibratedError::ScoringCommitmentMismatch(
            "sequence",
        ));
    }
    Ok(())
}

fn validate_profile_for_request(
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
) -> Result<(), QualifiedCalibratedError> {
    validate_profile_shape(profile)?;
    if profile.policy_digest != request.policy_digest {
        return Err(QualifiedCalibratedError::ProfilePolicyMismatch);
    }
    if profile.objective_class_digest != request.objective_class_digest {
        return Err(QualifiedCalibratedError::ProfileObjectiveMismatch);
    }
    if profile.generation != request.policy_generation {
        return Err(QualifiedCalibratedError::ProfileGenerationMismatch);
    }
    if request.sequence < profile.valid_from_sequence
        || request.sequence > profile.expires_after_sequence
    {
        return Err(QualifiedCalibratedError::ProfileExpired);
    }
    if request.minimum_confidence != profile.minimum_confidence {
        return Err(QualifiedCalibratedError::ProfileThresholdMismatch(
            "minimum confidence",
        ));
    }
    if request.maximum_ece_ppm != profile.maximum_ece_ppm {
        return Err(QualifiedCalibratedError::ProfileThresholdMismatch(
            "maximum ece",
        ));
    }
    if request.maximum_ood_false_acceptance_ppm != profile.maximum_ood_false_acceptance_ppm {
        return Err(QualifiedCalibratedError::ProfileThresholdMismatch(
            "maximum ood false acceptance",
        ));
    }
    if request.ood.maximum_in_domain_score != profile.maximum_in_domain_score {
        return Err(QualifiedCalibratedError::ProfileThresholdMismatch(
            "maximum in-domain score",
        ));
    }
    if request.calibration.artifact_digest != profile.calibration_artifact_digest {
        return Err(QualifiedCalibratedError::ProfileArtifactMismatch(
            "calibration",
        ));
    }
    if request.ood.artifact_digest != profile.ood_artifact_digest {
        return Err(QualifiedCalibratedError::ProfileArtifactMismatch("ood"));
    }
    if request.calibration.measured_ece_ppm != profile.calibration_measured_ece_ppm
        || request.calibration.subgroup_audit_digest != profile.calibration_subgroup_audit_digest
        || request.calibration.valid_from_sequence != profile.valid_from_sequence
        || request.calibration.expires_after_sequence != profile.expires_after_sequence
    {
        return Err(QualifiedCalibratedError::ProfileArtifactMetadataMismatch(
            "calibration",
        ));
    }
    if request.ood.measured_false_acceptance_ppm != profile.ood_measured_false_acceptance_ppm
        || request.ood.detector_digest != profile.ood_detector_digest
        || request.ood.support_digest != profile.ood_support_digest
        || request.ood.valid_from_sequence != profile.valid_from_sequence
        || request.ood.expires_after_sequence != profile.expires_after_sequence
    {
        return Err(QualifiedCalibratedError::ProfileArtifactMetadataMismatch(
            "ood",
        ));
    }
    Ok(())
}

fn validate_profile_shape(
    profile: &CanonicalPolicyProfileV1,
) -> Result<(), QualifiedCalibratedError> {
    for (name, digest) in [
        ("policy", profile.policy_digest),
        ("objective class", profile.objective_class_digest),
        ("scorer model", profile.scorer.model_digest),
        ("feature schema", profile.scorer.feature_schema_digest),
        ("output schema", profile.scorer.output_schema_digest),
        ("score semantics", profile.scorer.score_semantics_digest),
        ("scorer contract", profile.scorer.scorer_contract_digest),
        ("calibration dataset", profile.calibration_dataset_digest),
        ("ood dataset", profile.ood_dataset_digest),
        ("calibration artifact", profile.calibration_artifact_digest),
        (
            "calibration subgroup audit",
            profile.calibration_subgroup_audit_digest,
        ),
        ("ood artifact", profile.ood_artifact_digest),
        ("ood detector", profile.ood_detector_digest),
        ("ood support", profile.ood_support_digest),
    ] {
        if digest.is_zero() {
            return Err(QualifiedCalibratedError::EmptyProfileDigest(name));
        }
    }
    if profile.generation == 0 {
        return Err(QualifiedCalibratedError::InvalidProfileGeneration);
    }
    if profile.valid_from_sequence > profile.expires_after_sequence {
        return Err(QualifiedCalibratedError::InvalidProfileWindow);
    }
    if profile.calibration_measured_ece_ppm > profile.maximum_ece_ppm {
        return Err(QualifiedCalibratedError::ProfileThresholdMismatch(
            "qualified calibration ece",
        ));
    }
    if profile.ood_measured_false_acceptance_ppm > profile.maximum_ood_false_acceptance_ppm {
        return Err(QualifiedCalibratedError::ProfileThresholdMismatch(
            "qualified ood false acceptance",
        ));
    }
    Ok(())
}

const fn risk_requires_slow_path(rule: CanonicalRiskRuleV1, risk: RiskClass) -> bool {
    match rule {
        CanonicalRiskRuleV1::HighOnlySlowPath => matches!(risk, RiskClass::High),
        CanonicalRiskRuleV1::ElevatedAndHighSlowPath => {
            matches!(risk, RiskClass::Elevated | RiskClass::High)
        }
        CanonicalRiskRuleV1::AlwaysSlowPath => true,
    }
}

const fn risk_rule_code(rule: CanonicalRiskRuleV1) -> u8 {
    match rule {
        CanonicalRiskRuleV1::HighOnlySlowPath => 0,
        CanonicalRiskRuleV1::ElevatedAndHighSlowPath => 1,
        CanonicalRiskRuleV1::AlwaysSlowPath => 2,
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), QualifiedCalibratedError> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| CalibratedError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

#[cfg(test)]
#[path = "qualified_tests.rs"]
mod tests;

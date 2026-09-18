//! Current-generation qualification profile for calibrated intuition decisions.
//!
//! This layer remains pure and authority-free. It freezes the thresholds and
//! learned-scorer lineage used by the decision kernel. Cryptographic
//! authentication belongs to a consumer that owns a trusted key snapshot (the
//! Lane-F consumer lives in `codex-hepta-intelligence`).

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

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
    /// Exact immutable learned model bytes selected for this generation.
    pub model_digest: Digest32,
    /// Canonical feature ordering, units, scaling, missing-value and bounds schema.
    pub feature_schema_digest: Digest32,
    /// Canonical output field ordering and fixed-point representation schema.
    pub output_schema_digest: Digest32,
    /// Meaning of utility, calibrated confidence and OOD score.
    pub score_semantics_digest: Digest32,
    /// Versioned pure scorer interface and preprocessing/postprocessing contract.
    pub scorer_contract_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CanonicalRiskRuleV1 {
    /// Low and elevated risk may use the fast path; high risk must use slow path.
    HighOnlySlowPath,
    /// Only low risk may use the fast path.
    ElevatedAndHighSlowPath,
    /// Qualification profile disables direct fast-path selection for all risks.
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
    /// Frozen data used to measure `CalibrationArtifactV1::measured_ece_ppm`.
    pub calibration_dataset_digest: Digest32,
    /// Frozen data used to measure `OodArtifactV1::measured_false_acceptance_ppm`.
    pub ood_dataset_digest: Digest32,
    /// Only this calibration artifact is admitted for this profile generation.
    pub calibration_artifact_digest: Digest32,
    /// Only this OOD artifact is admitted for this profile generation.
    pub ood_artifact_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum QualifiedCalibratedError {
    Policy(CalibratedError),
    EmptyProfileDigest(&'static str),
    InvalidProfileGeneration,
    InvalidProfileWindow,
    ProfileExpired,
    ProfilePolicyMismatch,
    ProfileObjectiveMismatch,
    ProfileGenerationMismatch,
    ProfileThresholdMismatch(&'static str),
    ProfileArtifactMismatch(&'static str),
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

/// Canonical identity of the current-generation policy profile. The digest is
/// stable over exact model/scorer lineage, frozen qualification data, thresholds
/// and risk routing semantics.
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
        profile.ood_artifact_digest,
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
    bytes.push(risk_rule_code(profile.risk_rule));
    Ok(Digest32::of_bytes(&bytes))
}

/// Payload signed by the legal-set generator. It binds the exact state and the
/// exact complete candidate-set receipt without asking that signer to attest to
/// calibration, OOD or assignment semantics owned by other roles.
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

/// Payload signed by an independently trusted qualification evaluator. The
/// exact request commitment includes calibration/OOD metadata and assignment;
/// the profile commitment freezes the accepted model, datasets and thresholds.
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

/// Apply an authenticated-profile-compatible decision. Callers may still carry
/// the historical threshold fields for wire compatibility, but V3 rejects any
/// value that differs from the canonical profile. The profile therefore owns the
/// thresholds and risk routing semantics.
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
        // The V2 kernel already implements a fail-closed HighRisk disposition.
        // V3 may tighten that rule while its own digest remains bound to the
        // original risk class and the authenticated profile.
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
        ("ood artifact", profile.ood_artifact_digest),
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

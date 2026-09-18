//! Current-generation qualification profile for calibrated intuition decisions.
//!
//! This layer remains pure and authority-free. It freezes policy thresholds,
//! learned-scorer lineage, qualified calibration/OOD metadata, and an exact
//! per-decision scoring commitment. Cryptographic authentication belongs to a
//! consumer that owns a trusted key snapshot.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::calibrated::AssignmentModeV1;
use crate::calibrated::CalibratedActionCandidateV1;
use crate::calibrated::CalibratedDecisionRequestV1;
use crate::calibrated::CalibratedError;
use crate::calibrated::CalibratedIntuitionReceiptV1;
use crate::calibrated::RiskClass;
use crate::calibrated::canonical_calibrated_request_digest_v1;
use crate::calibrated::decide_calibrated_v2;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearnedScorerContractV1 {
    /// Exact immutable learned model bytes selected for this generation.
    pub model_artifact_digest: Digest32,
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
    /// Policy semantics/configuration identity. This is deliberately distinct
    /// from the learned model artifact and scorer contract identities.
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
    pub calibration_valid_from_sequence: u64,
    pub calibration_expires_after_sequence: u64,
    pub ood_artifact_digest: Digest32,
    pub ood_measured_false_acceptance_ppm: u32,
    pub ood_detector_digest: Digest32,
    pub ood_support_digest: Digest32,
    pub ood_valid_from_sequence: u64,
    pub ood_expires_after_sequence: u64,
}

/// Exact upstream scorer/policy-output commitment for one decision. It binds
/// assignment probabilities as policy outputs but excludes the random draw; the
/// RandomSource separately authenticates the stream/counter/draw context.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScoringCommitmentV1 {
    pub commitment_digest: Digest32,
    pub decision_id: StableId,
    pub objective_digest: Digest32,
    pub objective_class_digest: Digest32,
    pub state_digest: Digest32,
    pub policy_digest: Digest32,
    pub model_artifact_digest: Digest32,
    pub scorer_contract_digest: Digest32,
    pub feature_snapshot_digest: Digest32,
    pub feature_schema_digest: Digest32,
    pub output_schema_digest: Digest32,
    pub score_semantics_digest: Digest32,
    pub candidate_identity_digest: Digest32,
    pub scored_candidates_digest: Digest32,
    pub generation: u64,
    pub sequence: u64,
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
    ProfileQualityInvalid(&'static str),
    ScoringCommitmentDigestMismatch,
    ScoringCommitmentMismatch(&'static str),
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
/// stable over policy semantics, exact model/scorer identity, frozen
/// qualification data, admitted artifact metadata, thresholds and risk routing.
pub fn canonical_policy_profile_digest_v1(
    profile: &CanonicalPolicyProfileV1,
) -> Result<Digest32, QualifiedCalibratedError> {
    validate_profile_shape(profile)?;
    let mut bytes = b"hepta.intuition.canonical-policy-profile.v2\0".to_vec();
    push_id(&mut bytes, &profile.profile_id)?;
    for digest in [
        profile.policy_digest,
        profile.objective_class_digest,
        profile.scorer.model_artifact_digest,
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
        profile.calibration_valid_from_sequence,
        profile.calibration_expires_after_sequence,
        profile.ood_valid_from_sequence,
        profile.ood_expires_after_sequence,
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

/// Identity of the legal candidate surface independent of learned scores and
/// random assignment. This is the generator-owned view of one decision.
pub fn canonical_candidate_identity_digest_v1(
    candidates: &[CalibratedActionCandidateV1],
) -> Result<Digest32, QualifiedCalibratedError> {
    let mut bytes = b"hepta.intuition.candidate-identity.v1\0".to_vec();
    push_len(&mut bytes, candidates.len())?;
    for candidate in candidates {
        push_id(&mut bytes, &candidate.candidate_id)?;
        bytes.push(u8::from(candidate.legal));
        bytes.push(u8::from(candidate.hard_veto));
        bytes.extend_from_slice(candidate.support_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

/// Exact scorer/policy-output digest. Assignment probabilities are included:
/// they are policy outputs, not randomness. The RandomSource independently
/// signs the distribution context together with its stream/counter/draw.
pub fn canonical_scored_candidates_digest_v1(
    candidates: &[CalibratedActionCandidateV1],
) -> Result<Digest32, QualifiedCalibratedError> {
    let mut bytes = b"hepta.intuition.scored-candidates.v1\0".to_vec();
    push_len(&mut bytes, candidates.len())?;
    for candidate in candidates {
        push_id(&mut bytes, &candidate.candidate_id)?;
        bytes.extend_from_slice(&candidate.utility.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.calibrated_confidence.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.ood_score.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.assignment_probability.raw().to_be_bytes());
        bytes.extend_from_slice(candidate.support_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub fn scoring_commitment_for_request_v1(
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
    feature_snapshot_digest: Digest32,
) -> Result<ScoringCommitmentV1, QualifiedCalibratedError> {
    validate_profile_for_request(request, profile)?;
    if feature_snapshot_digest.is_zero() {
        return Err(QualifiedCalibratedError::EmptyScoringDigest(
            "feature snapshot",
        ));
    }
    let mut commitment = ScoringCommitmentV1 {
        commitment_digest: Digest32::ZERO,
        decision_id: request.decision_id.clone(),
        objective_digest: request.objective_digest,
        objective_class_digest: request.objective_class_digest,
        state_digest: request.state_digest,
        policy_digest: request.policy_digest,
        model_artifact_digest: profile.scorer.model_artifact_digest,
        scorer_contract_digest: profile.scorer.scorer_contract_digest,
        feature_snapshot_digest,
        feature_schema_digest: profile.scorer.feature_schema_digest,
        output_schema_digest: profile.scorer.output_schema_digest,
        score_semantics_digest: profile.scorer.score_semantics_digest,
        candidate_identity_digest: canonical_candidate_identity_digest_v1(&request.candidates)?,
        scored_candidates_digest: canonical_scored_candidates_digest_v1(&request.candidates)?,
        generation: request.policy_generation,
        sequence: request.sequence,
    };
    commitment.commitment_digest = canonical_scoring_commitment_digest_v1(&commitment)?;
    Ok(commitment)
}

pub fn canonical_scoring_commitment_digest_v1(
    commitment: &ScoringCommitmentV1,
) -> Result<Digest32, QualifiedCalibratedError> {
    for (name, digest) in [
        ("objective", commitment.objective_digest),
        ("objective class", commitment.objective_class_digest),
        ("state", commitment.state_digest),
        ("policy", commitment.policy_digest),
        ("model artifact", commitment.model_artifact_digest),
        ("scorer contract", commitment.scorer_contract_digest),
        ("feature snapshot", commitment.feature_snapshot_digest),
        ("feature schema", commitment.feature_schema_digest),
        ("output schema", commitment.output_schema_digest),
        ("score semantics", commitment.score_semantics_digest),
        ("candidate identity", commitment.candidate_identity_digest),
        ("scored candidates", commitment.scored_candidates_digest),
    ] {
        if digest.is_zero() {
            return Err(QualifiedCalibratedError::EmptyScoringDigest(name));
        }
    }
    let mut bytes = b"hepta.intuition.scoring-commitment.v1\0".to_vec();
    push_id(&mut bytes, &commitment.decision_id)?;
    for digest in [
        commitment.objective_digest,
        commitment.objective_class_digest,
        commitment.state_digest,
        commitment.policy_digest,
        commitment.model_artifact_digest,
        commitment.scorer_contract_digest,
        commitment.feature_snapshot_digest,
        commitment.feature_schema_digest,
        commitment.output_schema_digest,
        commitment.score_semantics_digest,
        commitment.candidate_identity_digest,
        commitment.scored_candidates_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&commitment.generation.to_be_bytes());
    bytes.extend_from_slice(&commitment.sequence.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

pub fn canonical_scoring_evidence_payload_v1(
    commitment: &ScoringCommitmentV1,
) -> Result<Vec<u8>, QualifiedCalibratedError> {
    let digest = canonical_scoring_commitment_digest_v1(commitment)?;
    if digest != commitment.commitment_digest {
        return Err(QualifiedCalibratedError::ScoringCommitmentDigestMismatch);
    }
    let mut bytes = b"hepta.intuition.scoring-evidence.v1\0".to_vec();
    bytes.extend_from_slice(digest.as_array());
    Ok(bytes)
}

/// Generator-owned exact candidate completeness payload. It binds candidate
/// identity/legality/support and generator/truncation facts, but not learned
/// scores or random assignment.
pub fn canonical_completeness_evidence_payload_v1(
    request: &CalibratedDecisionRequestV1,
) -> Result<Vec<u8>, QualifiedCalibratedError> {
    let candidate_identity_digest = canonical_candidate_identity_digest_v1(&request.candidates)?;
    let mut bytes = b"hepta.intuition.completeness-evidence.v2\0".to_vec();
    push_id(&mut bytes, &request.decision_id)?;
    for digest in [
        request.objective_digest,
        request.objective_class_digest,
        request.state_digest,
        request.completeness.receipt_digest,
        request.completeness.generator_digest,
        request.completeness.grammar_digest,
        request.completeness.hard_filter_digest,
        request.completeness.truncation_digest,
        request.completeness.canonical_order_digest,
        candidate_identity_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&request.policy_generation.to_be_bytes());
    bytes.extend_from_slice(&request.sequence.to_be_bytes());
    bytes.extend_from_slice(&request.completeness.candidate_count.to_be_bytes());
    bytes.extend_from_slice(&request.completeness.omitted_count_bound.to_be_bytes());
    Ok(bytes)
}

/// Long-lived evaluator-owned qualification payload. Per-decision candidate,
/// score, and random-source commitments are authenticated separately.
pub fn canonical_profile_qualification_evidence_payload_v1(
    profile: &CanonicalPolicyProfileV1,
) -> Result<Vec<u8>, QualifiedCalibratedError> {
    let profile_digest = canonical_policy_profile_digest_v1(profile)?;
    let mut bytes = b"hepta.intuition.profile-qualification-evidence.v1\0".to_vec();
    bytes.extend_from_slice(profile_digest.as_array());
    Ok(bytes)
}

/// Exact random-source payload for CounterBased assignment. The request sequence
/// is the canonical counter for this bounded profile.
pub fn canonical_random_assignment_evidence_payload_v1(
    request: &CalibratedDecisionRequestV1,
) -> Result<Option<Vec<u8>>, QualifiedCalibratedError> {
    let AssignmentModeV1::CounterBased {
        random_stream_digest,
        draw,
        abstain_probability,
    } = &request.assignment
    else {
        return Ok(None);
    };
    let mut bytes = b"hepta.intuition.random-assignment-evidence.v1\0".to_vec();
    push_id(&mut bytes, &request.decision_id)?;
    for digest in [
        request.objective_digest,
        request.state_digest,
        request.policy_digest,
        canonical_candidate_identity_digest_v1(&request.candidates)?,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&request.policy_generation.to_be_bytes());
    bytes.extend_from_slice(&request.sequence.to_be_bytes());
    bytes.extend_from_slice(random_stream_digest.as_array());
    bytes.extend_from_slice(&draw.raw().to_be_bytes());
    bytes.extend_from_slice(&abstain_probability.raw().to_be_bytes());
    push_len(&mut bytes, request.candidates.len())?;
    for candidate in &request.candidates {
        push_id(&mut bytes, &candidate.candidate_id)?;
        bytes.extend_from_slice(&candidate.assignment_probability.raw().to_be_bytes());
    }
    Ok(Some(bytes))
}

/// Apply the authenticated-profile-compatible decision. The caller must first
/// authenticate the scoring commitment and (for randomized assignment) the
/// random-source payload. V3 itself validates exact structural correspondence.
pub fn decide_calibrated_v3(
    request: CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
    scoring: &ScoringCommitmentV1,
) -> Result<CalibratedIntuitionReceiptV1, QualifiedCalibratedError> {
    validate_profile_for_request(&request, profile)?;
    validate_scoring_commitment_for_request(&request, profile, scoring)?;
    let original_request_digest = canonical_calibrated_request_digest_v1(&request)?;
    let profile_digest = canonical_policy_profile_digest_v1(profile)?;
    let scoring_digest = canonical_scoring_commitment_digest_v1(scoring)?;

    let force_slow_path = risk_requires_slow_path(profile.risk_rule, request.risk_class);
    let mut effective = request;
    if force_slow_path && effective.risk_class != RiskClass::High {
        effective.risk_class = RiskClass::High;
    }
    let mut receipt = decide_calibrated_v2(effective)?;
    let mut bytes = b"hepta.intuition.calibrated-decision.v3\0".to_vec();
    bytes.extend_from_slice(original_request_digest.as_array());
    bytes.extend_from_slice(profile_digest.as_array());
    bytes.extend_from_slice(scoring_digest.as_array());
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
    if request.calibration.measured_ece_ppm != profile.calibration_measured_ece_ppm {
        return Err(QualifiedCalibratedError::ProfileArtifactMetadataMismatch(
            "calibration measured ece",
        ));
    }
    if request.calibration.subgroup_audit_digest != profile.calibration_subgroup_audit_digest {
        return Err(QualifiedCalibratedError::ProfileArtifactMetadataMismatch(
            "calibration subgroup audit",
        ));
    }
    if request.calibration.valid_from_sequence != profile.calibration_valid_from_sequence
        || request.calibration.expires_after_sequence != profile.calibration_expires_after_sequence
    {
        return Err(QualifiedCalibratedError::ProfileArtifactMetadataMismatch(
            "calibration validity window",
        ));
    }
    if request.ood.measured_false_acceptance_ppm != profile.ood_measured_false_acceptance_ppm {
        return Err(QualifiedCalibratedError::ProfileArtifactMetadataMismatch(
            "ood measured false acceptance",
        ));
    }
    if request.ood.detector_digest != profile.ood_detector_digest {
        return Err(QualifiedCalibratedError::ProfileArtifactMetadataMismatch(
            "ood detector",
        ));
    }
    if request.ood.support_digest != profile.ood_support_digest {
        return Err(QualifiedCalibratedError::ProfileArtifactMetadataMismatch(
            "ood support",
        ));
    }
    if request.ood.valid_from_sequence != profile.ood_valid_from_sequence
        || request.ood.expires_after_sequence != profile.ood_expires_after_sequence
    {
        return Err(QualifiedCalibratedError::ProfileArtifactMetadataMismatch(
            "ood validity window",
        ));
    }
    Ok(())
}

fn validate_scoring_commitment_for_request(
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
    scoring: &ScoringCommitmentV1,
) -> Result<(), QualifiedCalibratedError> {
    if canonical_scoring_commitment_digest_v1(scoring)? != scoring.commitment_digest {
        return Err(QualifiedCalibratedError::ScoringCommitmentDigestMismatch);
    }
    if scoring.decision_id != request.decision_id {
        return Err(QualifiedCalibratedError::ScoringCommitmentMismatch(
            "decision id",
        ));
    }
    if scoring.objective_digest != request.objective_digest {
        return Err(QualifiedCalibratedError::ScoringCommitmentMismatch(
            "objective",
        ));
    }
    if scoring.objective_class_digest != request.objective_class_digest
        || scoring.objective_class_digest != profile.objective_class_digest
    {
        return Err(QualifiedCalibratedError::ScoringCommitmentMismatch(
            "objective class",
        ));
    }
    if scoring.state_digest != request.state_digest {
        return Err(QualifiedCalibratedError::ScoringCommitmentMismatch("state"));
    }
    if scoring.policy_digest != profile.policy_digest || scoring.policy_digest != request.policy_digest
    {
        return Err(QualifiedCalibratedError::ScoringCommitmentMismatch(
            "policy",
        ));
    }
    if scoring.model_artifact_digest != profile.scorer.model_artifact_digest {
        return Err(QualifiedCalibratedError::ScoringCommitmentMismatch(
            "model artifact",
        ));
    }
    if scoring.scorer_contract_digest != profile.scorer.scorer_contract_digest {
        return Err(QualifiedCalibratedError::ScoringCommitmentMismatch(
            "scorer contract",
        ));
    }
    if scoring.feature_schema_digest != profile.scorer.feature_schema_digest
        || scoring.output_schema_digest != profile.scorer.output_schema_digest
        || scoring.score_semantics_digest != profile.scorer.score_semantics_digest
    {
        return Err(QualifiedCalibratedError::ScoringCommitmentMismatch(
            "scorer schemas",
        ));
    }
    if scoring.generation != request.policy_generation || scoring.sequence != request.sequence {
        return Err(QualifiedCalibratedError::ScoringCommitmentMismatch(
            "generation or sequence",
        ));
    }
    if scoring.candidate_identity_digest
        != canonical_candidate_identity_digest_v1(&request.candidates)?
    {
        return Err(QualifiedCalibratedError::ScoringCommitmentMismatch(
            "candidate identity",
        ));
    }
    if scoring.scored_candidates_digest
        != canonical_scored_candidates_digest_v1(&request.candidates)?
    {
        return Err(QualifiedCalibratedError::ScoringCommitmentMismatch(
            "scored candidates",
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
        ("scorer model", profile.scorer.model_artifact_digest),
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
    if profile.valid_from_sequence > profile.expires_after_sequence
        || profile.calibration_valid_from_sequence > profile.calibration_expires_after_sequence
        || profile.ood_valid_from_sequence > profile.ood_expires_after_sequence
        || profile.calibration_valid_from_sequence > profile.valid_from_sequence
        || profile.calibration_expires_after_sequence < profile.expires_after_sequence
        || profile.ood_valid_from_sequence > profile.valid_from_sequence
        || profile.ood_expires_after_sequence < profile.expires_after_sequence
    {
        return Err(QualifiedCalibratedError::InvalidProfileWindow);
    }
    if profile.calibration_measured_ece_ppm > profile.maximum_ece_ppm {
        return Err(QualifiedCalibratedError::ProfileQualityInvalid(
            "calibration ece",
        ));
    }
    if profile.ood_measured_false_acceptance_ppm > profile.maximum_ood_false_acceptance_ppm {
        return Err(QualifiedCalibratedError::ProfileQualityInvalid(
            "ood false acceptance",
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

fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), QualifiedCalibratedError> {
    let value = u32::try_from(value).map_err(|_| CalibratedError::Arithmetic)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

#[cfg(test)]
#[path = "qualified_tests.rs"]
mod tests;

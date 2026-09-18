use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::calibrated::CalibratedActionCandidateV1;
use crate::calibrated::CalibratedIntuitionReceiptV1;
use crate::calibrated::decide_calibrated_v2;

use super::QualificationMacKeyV1;
use super::QualificationTrustV1;
use super::QualifiedDecisionRequestV1;
use super::QualifiedError;
use super::QualifiedIntuitionReceiptV1;
use super::RiskPolicyV1;
use super::auth::assignment_scope_digest_v1;
use super::auth::authenticate_mac;
use super::auth::calibration_scope_digest_v1;
use super::auth::completeness_scope_digest_v1;
use super::auth::ood_scope_digest_v1;
use super::auth::policy_profile_scope_digest_v1;
use super::auth::scorer_output_scope_digest_v1;
use super::digest::canonical_assignment_digest_v1;
use super::digest::canonical_calibration_artifact_digest_v1;
use super::digest::canonical_completeness_receipt_digest_v1;
use super::digest::canonical_ood_artifact_digest_v1;
use super::digest::canonical_policy_profile_digest_v1;
use super::digest::canonical_scorer_contract_digest_v1;
use super::digest::canonical_scorer_output_digest_v1;

/// Verify all current-generation qualification material and execute the bounded
/// calibrated policy. Request thresholds are accepted only when they exactly
/// mirror the authenticated canonical profile; they are never authoritative.
pub fn decide_qualified_v1(
    qualified: QualifiedDecisionRequestV1<'_>,
    trust: QualificationTrustV1<'_>,
) -> Result<QualifiedIntuitionReceiptV1, QualifiedError> {
    validate_trust_roles(&trust)?;
    validate_profile(&qualified, &trust)?;
    validate_artifact_digests(&qualified)?;
    validate_scorer_contract(&qualified, &trust)?;
    validate_score_evidence(&qualified)?;

    let request = &qualified.request;
    let scorer_output_digest = canonical_scorer_output_digest_v1(
        &request.decision_id,
        request.state_digest,
        qualified.scorer_contract.contract_digest,
        qualified.scorer_contract.model_artifact_digest,
        &qualified.score_evidence,
    )?;
    let assignment_digest = canonical_assignment_digest_v1(
        request,
        qualified.profile.profile_digest,
        scorer_output_digest,
    )?;

    let profile_auth = authenticate_mac(
        trust.artifact_key,
        qualified.artifacts.profile,
        trust.subject_id,
        policy_profile_scope_digest_v1(),
        qualified.profile.profile_digest,
        trust.expected_generation,
        request.sequence,
    )?;
    let calibration_auth = authenticate_mac(
        trust.artifact_key,
        qualified.artifacts.calibration,
        trust.subject_id,
        calibration_scope_digest_v1(),
        request.calibration.artifact_digest,
        trust.expected_generation,
        request.sequence,
    )?;
    let ood_auth = authenticate_mac(
        trust.artifact_key,
        qualified.artifacts.ood,
        trust.subject_id,
        ood_scope_digest_v1(),
        request.ood.artifact_digest,
        trust.expected_generation,
        request.sequence,
    )?;
    let completeness_auth = authenticate_mac(
        trust.artifact_key,
        qualified.artifacts.completeness,
        trust.subject_id,
        completeness_scope_digest_v1(),
        request.completeness.receipt_digest,
        trust.expected_generation,
        request.sequence,
    )?;
    let scorer_auth = authenticate_mac(
        trust.scorer_key,
        qualified.artifacts.scorer_output,
        trust.subject_id,
        scorer_output_scope_digest_v1(),
        scorer_output_digest,
        trust.expected_generation,
        request.sequence,
    )?;
    let assignment_auth = authenticate_mac(
        trust.assignment_key,
        qualified.artifacts.assignment,
        trust.subject_id,
        assignment_scope_digest_v1(),
        assignment_digest,
        trust.expected_generation,
        request.sequence,
    )?;

    if qualified.artifacts.completeness.valid_from_sequence != request.sequence
        || qualified.artifacts.completeness.expires_after_sequence != request.sequence
    {
        return Err(QualifiedError::DecisionSpecificSequenceMismatch(
            "completeness",
        ));
    }
    if qualified.artifacts.scorer_output.valid_from_sequence != request.sequence
        || qualified.artifacts.scorer_output.expires_after_sequence != request.sequence
    {
        return Err(QualifiedError::DecisionSpecificSequenceMismatch(
            "scorer output",
        ));
    }
    if qualified.artifacts.assignment.valid_from_sequence != request.sequence
        || qualified.artifacts.assignment.expires_after_sequence != request.sequence
    {
        return Err(QualifiedError::DecisionSpecificSequenceMismatch("assignment"));
    }

    let decision = decide_calibrated_v2(qualified.request)?;
    let receipt_digest = qualified_receipt_digest(
        &decision,
        qualified.profile.profile_digest,
        qualified.scorer_contract.contract_digest,
        scorer_output_digest,
        assignment_digest,
        profile_auth,
        calibration_auth,
        ood_auth,
        completeness_auth,
        scorer_auth,
        assignment_auth,
    );

    Ok(QualifiedIntuitionReceiptV1 {
        decision,
        policy_profile_digest: qualified.profile.profile_digest,
        scorer_contract_digest: qualified.scorer_contract.contract_digest,
        scorer_output_digest,
        assignment_digest,
        profile_authentication_digest: profile_auth,
        calibration_authentication_digest: calibration_auth,
        ood_authentication_digest: ood_auth,
        completeness_authentication_digest: completeness_auth,
        scorer_authentication_digest: scorer_auth,
        assignment_authentication_digest: assignment_auth,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_trust_roles(trust: &QualificationTrustV1<'_>) -> Result<(), QualifiedError> {
    let artifact = trust.artifact_key.key_id();
    let scorer = trust.scorer_key.key_id();
    let assignment = trust.assignment_key.key_id();
    if artifact == scorer || artifact == assignment || scorer == assignment {
        return Err(QualifiedError::AuthenticationKeyRoleConflict);
    }
    if same_key_material(trust.artifact_key, trust.scorer_key)
        || same_key_material(trust.artifact_key, trust.assignment_key)
        || same_key_material(trust.scorer_key, trust.assignment_key)
    {
        return Err(QualifiedError::AuthenticationKeyRoleConflict);
    }
    Ok(())
}

fn same_key_material(left: &QualificationMacKeyV1, right: &QualificationMacKeyV1) -> bool {
    let mut different = 0_u8;
    for (left, right) in left.secret.iter().zip(right.secret.iter()) {
        different |= *left ^ *right;
    }
    different == 0
}

fn validate_profile(
    qualified: &QualifiedDecisionRequestV1<'_>,
    trust: &QualificationTrustV1<'_>,
) -> Result<(), QualifiedError> {
    let request = &qualified.request;
    let profile = &qualified.profile;
    if profile.profile_digest != canonical_policy_profile_digest_v1(profile)? {
        return Err(QualifiedError::ProfileDigestMismatch);
    }
    if profile.policy_digest != request.policy_digest
        || profile.objective_class_digest != request.objective_class_digest
        || profile.generation != request.policy_generation
        || profile.generation != trust.expected_generation
        || profile.scorer_contract_digest != qualified.scorer_contract.contract_digest
    {
        return Err(QualifiedError::ProfileBindingMismatch);
    }
    if profile.valid_from_sequence > profile.expires_after_sequence {
        return Err(QualifiedError::ProfileWindowInvalid);
    }
    if request.sequence < profile.valid_from_sequence
        || request.sequence > profile.expires_after_sequence
    {
        return Err(QualifiedError::ProfileExpired);
    }
    if request.minimum_confidence != profile.minimum_confidence
        || request.maximum_ece_ppm != profile.maximum_ece_ppm
        || request.maximum_ood_false_acceptance_ppm != profile.maximum_ood_false_acceptance_ppm
    {
        return Err(QualifiedError::ProfileThresholdMismatch);
    }
    if profile.risk_policy != RiskPolicyV1::HighAlwaysSlowPath {
        return Err(QualifiedError::UnsupportedRiskPolicy);
    }
    if !profile.require_zero_omissions || request.completeness.omitted_count_bound != 0 {
        return Err(QualifiedError::IncompleteCandidateSet);
    }
    Ok(())
}

fn validate_artifact_digests(
    qualified: &QualifiedDecisionRequestV1<'_>,
) -> Result<(), QualifiedError> {
    let request = &qualified.request;
    if request.calibration.artifact_digest
        != canonical_calibration_artifact_digest_v1(&request.calibration)
    {
        return Err(QualifiedError::ArtifactDigestMismatch("calibration"));
    }
    if request.ood.artifact_digest != canonical_ood_artifact_digest_v1(&request.ood) {
        return Err(QualifiedError::ArtifactDigestMismatch("ood"));
    }
    if request.completeness.receipt_digest
        != canonical_completeness_receipt_digest_v1(
            &request.completeness,
            request.state_digest,
            request.policy_digest,
            request.policy_generation,
            request.sequence,
        )
    {
        return Err(QualifiedError::ArtifactDigestMismatch("completeness"));
    }
    Ok(())
}

fn validate_scorer_contract(
    qualified: &QualifiedDecisionRequestV1<'_>,
    trust: &QualificationTrustV1<'_>,
) -> Result<(), QualifiedError> {
    let request = &qualified.request;
    let contract = &qualified.scorer_contract;
    for (name, digest) in [
        ("scorer policy", contract.policy_digest),
        ("scorer objective class", contract.objective_class_digest),
        ("model artifact", contract.model_artifact_digest),
        ("feature schema", contract.feature_schema_digest),
        ("utility semantics", contract.utility_semantics_digest),
        ("confidence semantics", contract.confidence_semantics_digest),
        ("ood semantics", contract.ood_semantics_digest),
        (
            "scorer calibration artifact",
            contract.calibration_artifact_digest,
        ),
        ("scorer ood artifact", contract.ood_artifact_digest),
        ("scorer ood detector", contract.ood_detector_digest),
    ] {
        if digest.is_zero() {
            return Err(QualifiedError::EmptyDigest(name));
        }
    }
    if contract.contract_digest != canonical_scorer_contract_digest_v1(contract) {
        return Err(QualifiedError::ScorerContractDigestMismatch);
    }
    if contract.policy_digest != request.policy_digest
        || contract.objective_class_digest != request.objective_class_digest
        || contract.generation != request.policy_generation
        || contract.generation != trust.expected_generation
        || contract.calibration_artifact_digest != request.calibration.artifact_digest
        || contract.ood_artifact_digest != request.ood.artifact_digest
        || contract.ood_detector_digest != request.ood.detector_digest
    {
        return Err(QualifiedError::ScorerContractBindingMismatch);
    }
    Ok(())
}

fn validate_score_evidence(
    qualified: &QualifiedDecisionRequestV1<'_>,
) -> Result<(), QualifiedError> {
    if qualified.score_evidence.len() != qualified.request.candidates.len() {
        return Err(QualifiedError::ScoreEvidenceCountMismatch);
    }
    for (candidate, evidence) in qualified
        .request
        .candidates
        .iter()
        .zip(&qualified.score_evidence)
    {
        if evidence.feature_digest.is_zero() {
            return Err(QualifiedError::EmptyDigest("score feature"));
        }
        if !score_matches_candidate(candidate, evidence) {
            return Err(QualifiedError::ScoreEvidenceMismatch(
                candidate.candidate_id.to_string(),
            ));
        }
    }
    Ok(())
}

fn score_matches_candidate(
    candidate: &CalibratedActionCandidateV1,
    evidence: &super::LearnedScoreEvidenceV1,
) -> bool {
    candidate.candidate_id == evidence.candidate_id
        && candidate.utility == evidence.utility
        && candidate.calibrated_confidence == evidence.calibrated_confidence
        && candidate.ood_score == evidence.ood_score
        && candidate.support_digest == evidence.support_digest
}

#[allow(clippy::too_many_arguments)]
fn qualified_receipt_digest(
    decision: &CalibratedIntuitionReceiptV1,
    profile: Digest32,
    scorer_contract: Digest32,
    scorer_output: Digest32,
    assignment: Digest32,
    profile_auth: Digest32,
    calibration_auth: Digest32,
    ood_auth: Digest32,
    completeness_auth: Digest32,
    scorer_auth: Digest32,
    assignment_auth: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.intuition.qualified-decision.v1\0".to_vec();
    for digest in [
        decision.receipt_digest,
        profile,
        scorer_contract,
        scorer_output,
        assignment,
        profile_auth,
        calibration_auth,
        ood_auth,
        completeness_auth,
        scorer_auth,
        assignment_auth,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

//! Qualified production path for calibrated intuition decisions.
//!
//! The legacy calibrated API remains replayable, but production callers should
//! use [`decide_qualified`]. This path requires a canonical policy profile and a
//! qualification manifest authenticated by an external authority verifier.

use codex_hepta_types::{Digest32, ProbabilityQ32};

use crate::calibrated::{
    CalibratedDecisionRequestV1, CalibratedError, CalibratedIntuitionReceiptV1, RiskClass,
    decide_calibrated_v2,
};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalPolicyProfileV1 {
    pub profile_digest: Digest32,
    pub policy_digest: Digest32,
    pub policy_generation: u64,
    pub minimum_confidence: ProbabilityQ32,
    pub maximum_ece_ppm: u32,
    pub maximum_ood_false_acceptance_ppm: u32,
    /// Elevated risk may be admitted only when this canonical profile says so.
    /// High risk is never eligible for the fast path.
    pub allow_elevated_risk: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualificationManifestV1 {
    pub manifest_digest: Digest32,
    pub authority_digest: Digest32,
    pub signer_set_digest: Digest32,
    pub qualification_run_digest: Digest32,
    pub frozen_validation_digest: Digest32,
    pub model_artifact_digest: Digest32,
    pub scorer_contract_digest: Digest32,
    pub profile_digest: Digest32,
    pub policy_digest: Digest32,
    pub objective_class_digest: Digest32,
    pub policy_generation: u64,
    pub completeness_receipt_digest: Digest32,
    pub calibration_artifact_digest: Digest32,
    pub ood_artifact_digest: Digest32,
}

/// Host boundary for cryptographic / registry authentication.
///
/// Implementations MUST verify the manifest against the current trusted signer
/// set (for example an Ed25519 signed-artifact authority), revocation state and
/// current-generation qualification registry. The intuition crate deliberately
/// owns no signing key and grants no authority itself.
pub trait QualificationAuthorityVerifier {
    fn authenticate(&self, manifest: &QualificationManifestV1) -> bool;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualifiedDecisionRequestV1 {
    pub decision: CalibratedDecisionRequestV1,
    pub profile: CanonicalPolicyProfileV1,
    pub qualification: QualificationManifestV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum QualifiedError {
    Calibrated(CalibratedError),
    EmptyQualificationDigest(&'static str),
    QualificationAuthenticationFailed,
    QualificationManifestDigestMismatch,
    QualificationPolicyMismatch,
    QualificationObjectiveMismatch,
    QualificationGenerationMismatch,
    QualificationArtifactMismatch,
    QualificationProfileMismatch,
    CanonicalProfileMismatch,
    IncompleteCandidateSet,
    RiskNotAdmitted,
}

impl From<CalibratedError> for QualifiedError {
    fn from(value: CalibratedError) -> Self {
        Self::Calibrated(value)
    }
}

pub fn canonical_policy_profile_digest_v1(profile: &CanonicalPolicyProfileV1) -> Digest32 {
    let mut bytes = b"hepta.intuition.canonical-policy-profile.v1".to_vec();
    bytes.extend_from_slice(profile.policy_digest.as_array());
    bytes.extend_from_slice(&profile.policy_generation.to_be_bytes());
    bytes.extend_from_slice(&profile.minimum_confidence.raw().to_be_bytes());
    bytes.extend_from_slice(&profile.maximum_ece_ppm.to_be_bytes());
    bytes.extend_from_slice(&profile.maximum_ood_false_acceptance_ppm.to_be_bytes());
    bytes.push(u8::from(profile.allow_elevated_risk));
    Digest32::of_bytes(&bytes)
}

pub fn canonical_qualification_manifest_digest_v1(manifest: &QualificationManifestV1) -> Digest32 {
    let mut bytes = b"hepta.intuition.qualification-manifest.v1".to_vec();
    for digest in [
        manifest.authority_digest,
        manifest.signer_set_digest,
        manifest.qualification_run_digest,
        manifest.frozen_validation_digest,
        manifest.model_artifact_digest,
        manifest.scorer_contract_digest,
        manifest.profile_digest,
        manifest.policy_digest,
        manifest.objective_class_digest,
        manifest.completeness_receipt_digest,
        manifest.calibration_artifact_digest,
        manifest.ood_artifact_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&manifest.policy_generation.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

pub fn decide_qualified<V: QualificationAuthorityVerifier>(
    request: QualifiedDecisionRequestV1,
    verifier: &V,
) -> Result<CalibratedIntuitionReceiptV1, QualifiedError> {
    validate_qualification(&request, verifier)?;
    decide_calibrated_v2(request.decision).map_err(Into::into)
}

fn validate_qualification<V: QualificationAuthorityVerifier>(
    request: &QualifiedDecisionRequestV1,
    verifier: &V,
) -> Result<(), QualifiedError> {
    let decision = &request.decision;
    let profile = &request.profile;
    let qualification = &request.qualification;

    for (name, digest) in [
        ("profile", profile.profile_digest),
        ("authority", qualification.authority_digest),
        ("signer set", qualification.signer_set_digest),
        ("qualification run", qualification.qualification_run_digest),
        ("frozen validation", qualification.frozen_validation_digest),
        ("model artifact", qualification.model_artifact_digest),
        ("scorer contract", qualification.scorer_contract_digest),
        ("qualification manifest", qualification.manifest_digest),
    ] {
        if digest.is_zero() {
            return Err(QualifiedError::EmptyQualificationDigest(name));
        }
    }

    if canonical_policy_profile_digest_v1(profile) != profile.profile_digest {
        return Err(QualifiedError::CanonicalProfileMismatch);
    }
    if canonical_qualification_manifest_digest_v1(qualification) != qualification.manifest_digest {
        return Err(QualifiedError::QualificationManifestDigestMismatch);
    }
    if !verifier.authenticate(qualification) {
        return Err(QualifiedError::QualificationAuthenticationFailed);
    }

    if profile.policy_digest != decision.policy_digest
        || qualification.policy_digest != decision.policy_digest
    {
        return Err(QualifiedError::QualificationPolicyMismatch);
    }
    if qualification.objective_class_digest != decision.objective_class_digest {
        return Err(QualifiedError::QualificationObjectiveMismatch);
    }
    if profile.policy_generation != decision.policy_generation
        || qualification.policy_generation != decision.policy_generation
    {
        return Err(QualifiedError::QualificationGenerationMismatch);
    }
    if qualification.profile_digest != profile.profile_digest {
        return Err(QualifiedError::QualificationProfileMismatch);
    }
    if qualification.completeness_receipt_digest != decision.completeness.receipt_digest
        || qualification.calibration_artifact_digest != decision.calibration.artifact_digest
        || qualification.ood_artifact_digest != decision.ood.artifact_digest
    {
        return Err(QualifiedError::QualificationArtifactMismatch);
    }

    // The complete legal action set is an invariant of the policy kernel, not
    // merely a consumer-side convention.
    if decision.completeness.omitted_count_bound != 0 {
        return Err(QualifiedError::IncompleteCandidateSet);
    }

    // Request-local knobs are accepted only for legacy compatibility. On the
    // qualified path they must exactly equal the authenticated canonical profile.
    if decision.minimum_confidence != profile.minimum_confidence
        || decision.maximum_ece_ppm != profile.maximum_ece_ppm
        || decision.maximum_ood_false_acceptance_ppm != profile.maximum_ood_false_acceptance_ppm
    {
        return Err(QualifiedError::CanonicalProfileMismatch);
    }

    match decision.risk_class {
        RiskClass::Low => {}
        RiskClass::Elevated if profile.allow_elevated_risk => {}
        RiskClass::Elevated | RiskClass::High => return Err(QualifiedError::RiskNotAdmitted),
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::calibrated::{
        AssignmentModeV1, CalibratedActionCandidateV1, CalibrationArtifactV1,
        CandidateSetCompletenessBindingV1, OodArtifactV1, canonical_candidate_order_digest_v1,
        canonical_candidate_set_digest_v1,
    };
    use codex_hepta_types::{FixedQ32, StableId};

    struct AcceptKnownAuthority(Digest32);
    impl QualificationAuthorityVerifier for AcceptKnownAuthority {
        fn authenticate(&self, manifest: &QualificationManifestV1) -> bool {
            manifest.authority_digest == self.0
        }
    }

    fn digest(value: &str) -> Digest32 { Digest32::of_bytes(value.as_bytes()) }
    fn id(value: &str) -> StableId { StableId::new(value).expect("test id") }
    fn p(raw: u64) -> ProbabilityQ32 { ProbabilityQ32::from_raw(raw).expect("probability") }

    fn qualified() -> QualifiedDecisionRequestV1 {
        let candidates = vec![CalibratedActionCandidateV1 {
            candidate_id: id("candidate:a"), legal: true, hard_veto: false,
            utility: FixedQ32::from_raw(10), calibrated_confidence: ProbabilityQ32::ONE,
            ood_score: ProbabilityQ32::ZERO, assignment_probability: ProbabilityQ32::ZERO,
            support_digest: digest("support"),
        }];
        let policy = digest("policy");
        let objective_class = digest("objective-class");
        let completeness_digest = digest("completeness");
        let calibration_digest = digest("calibration");
        let ood_digest = digest("ood");
        let profile0 = CanonicalPolicyProfileV1 {
            profile_digest: Digest32::ZERO, policy_digest: policy, policy_generation: 7,
            minimum_confidence: p(ProbabilityQ32::ONE.raw() / 2), maximum_ece_ppm: 50_000,
            maximum_ood_false_acceptance_ppm: 5_000, allow_elevated_risk: false,
        };
        let profile = CanonicalPolicyProfileV1 {
            profile_digest: canonical_policy_profile_digest_v1(&profile0), ..profile0
        };
        let decision = CalibratedDecisionRequestV1 {
            decision_id: id("decision:q"), objective_digest: digest("objective"),
            objective_class_digest: objective_class, state_digest: digest("state"), policy_digest: policy,
            policy_generation: 7, sequence: 10, minimum_confidence: profile.minimum_confidence,
            maximum_ece_ppm: profile.maximum_ece_ppm,
            maximum_ood_false_acceptance_ppm: profile.maximum_ood_false_acceptance_ppm,
            risk_class: RiskClass::Low,
            completeness: CandidateSetCompletenessBindingV1 {
                receipt_digest: completeness_digest, generator_digest: digest("generator"),
                grammar_digest: digest("grammar"), hard_filter_digest: digest("filter"),
                truncation_digest: digest("truncation"),
                candidate_set_digest: canonical_candidate_set_digest_v1(&candidates).expect("set"),
                canonical_order_digest: canonical_candidate_order_digest_v1(&candidates).expect("order"),
                candidate_count: 1, omitted_count_bound: 0,
            },
            calibration: CalibrationArtifactV1 {
                artifact_digest: calibration_digest, policy_digest: policy,
                objective_class_digest: objective_class, generation: 7, valid_from_sequence: 1,
                expires_after_sequence: 100, measured_ece_ppm: 10_000,
                subgroup_audit_digest: digest("audit"),
            },
            ood: OodArtifactV1 {
                artifact_digest: ood_digest, policy_digest: policy, detector_digest: digest("detector"),
                support_digest: digest("ood-support"), generation: 7, valid_from_sequence: 1,
                expires_after_sequence: 100,
                maximum_in_domain_score: p(ProbabilityQ32::ONE.raw() / 4),
                measured_false_acceptance_ppm: 1_000,
            },
            assignment: AssignmentModeV1::Deterministic, candidates,
        };
        let authority = digest("authority");
        let manifest0 = QualificationManifestV1 {
            manifest_digest: Digest32::ZERO, authority_digest: authority,
            signer_set_digest: digest("signer-set"), qualification_run_digest: digest("run"),
            frozen_validation_digest: digest("frozen-data"), model_artifact_digest: digest("model"),
            scorer_contract_digest: digest("scorer-contract"), profile_digest: profile.profile_digest,
            policy_digest: policy, objective_class_digest: objective_class, policy_generation: 7,
            completeness_receipt_digest: completeness_digest,
            calibration_artifact_digest: calibration_digest, ood_artifact_digest: ood_digest,
        };
        let qualification = QualificationManifestV1 {
            manifest_digest: canonical_qualification_manifest_digest_v1(&manifest0), ..manifest0
        };
        QualifiedDecisionRequestV1 { decision, profile, qualification }
    }

    #[test]
    fn qualified_path_requires_authenticated_current_generation_manifest() {
        let request = qualified();
        let verifier = AcceptKnownAuthority(request.qualification.authority_digest);
        assert!(decide_qualified(request, &verifier).is_ok());
    }

    #[test]
    fn qualified_path_rejects_incomplete_candidate_set_inside_intuition_crate() {
        let mut request = qualified();
        request.decision.completeness.omitted_count_bound = 1;
        let verifier = AcceptKnownAuthority(request.qualification.authority_digest);
        assert_eq!(decide_qualified(request, &verifier), Err(QualifiedError::IncompleteCandidateSet));
    }

    #[test]
    fn qualified_path_rejects_request_local_threshold_drift() {
        let mut request = qualified();
        request.decision.maximum_ece_ppm += 1;
        let verifier = AcceptKnownAuthority(request.qualification.authority_digest);
        assert_eq!(decide_qualified(request, &verifier), Err(QualifiedError::CanonicalProfileMismatch));
    }

    #[test]
    fn qualified_path_rejects_untrusted_authority() {
        let request = qualified();
        let verifier = AcceptKnownAuthority(digest("different-authority"));
        assert_eq!(decide_qualified(request, &verifier), Err(QualifiedError::QualificationAuthenticationFailed));
    }
}

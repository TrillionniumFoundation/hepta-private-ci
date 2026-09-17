//! Qualified production path for calibrated intuition decisions.
//!
//! Historical calibrated APIs remain replayable. New production-oriented
//! decisions use a canonical policy profile and a current-generation
//! qualification manifest that is authenticated by a pinned Ed25519 verifier.

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use codex_hepta_types::{Digest32, ProbabilityQ32};
use ed25519_dalek::{Signature, Verifier as _, VerifyingKey};

use crate::calibrated::{
    CalibratedDecisionRequestV1, CalibratedError, CalibratedIntuitionReceiptV1, RiskClass,
    decide_calibrated_v2,
};

const QUALIFICATION_SIGNATURE_DOMAIN: &[u8] = b"hepta.intuition.qualification-signature.v1";

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

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedQualificationEnvelopeV1 {
    pub signer_id: String,
    pub signer_epoch: u64,
    pub authority_digest: Digest32,
    pub manifest_digest: Digest32,
    pub policy_generation: u64,
    pub valid_from_sequence: u64,
    pub expires_after_sequence: u64,
    pub signature_base64: String,
}

/// Trust anchor supplied independently of the signed envelope.
#[derive(Clone)]
pub struct PinnedQualificationVerifierV1 {
    signer_id: String,
    signer_epoch: u64,
    authority_digest: Digest32,
    verifying_key: VerifyingKey,
}

/// Capability token created only after cryptographic verification. Its fields
/// are private so downstream callers cannot construct a fake authenticated
/// qualification without passing the pinned verifier.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedQualificationV1 {
    manifest_digest: Digest32,
    authority_digest: Digest32,
    policy_generation: u64,
    signer_epoch: u64,
}

impl AuthenticatedQualificationV1 {
    pub fn manifest_digest(&self) -> Digest32 { self.manifest_digest }
    pub fn authority_digest(&self) -> Digest32 { self.authority_digest }
    pub const fn policy_generation(&self) -> u64 { self.policy_generation }
    pub const fn signer_epoch(&self) -> u64 { self.signer_epoch }
}

impl PinnedQualificationVerifierV1 {
    pub fn from_bytes(
        signer_id: impl Into<String>,
        signer_epoch: u64,
        authority_digest: Digest32,
        public_key: [u8; 32],
    ) -> Result<Self, QualifiedError> {
        let signer_id = signer_id.into();
        if signer_id.is_empty() || signer_epoch == 0 || authority_digest.is_zero() {
            return Err(QualifiedError::InvalidTrustAnchor);
        }
        let verifying_key = VerifyingKey::from_bytes(&public_key)
            .map_err(|_| QualifiedError::InvalidTrustAnchor)?;
        if verifying_key.is_weak() {
            return Err(QualifiedError::InvalidTrustAnchor);
        }
        Ok(Self { signer_id, signer_epoch, authority_digest, verifying_key })
    }

    pub fn verify(
        &self,
        envelope: &SignedQualificationEnvelopeV1,
        manifest: &QualificationManifestV1,
        decision_sequence: u64,
    ) -> Result<AuthenticatedQualificationV1, QualifiedError> {
        if canonical_qualification_manifest_digest_v1(manifest) != manifest.manifest_digest {
            return Err(QualifiedError::QualificationManifestDigestMismatch);
        }
        if envelope.signer_id != self.signer_id
            || envelope.signer_epoch != self.signer_epoch
            || envelope.authority_digest != self.authority_digest
            || envelope.authority_digest != manifest.authority_digest
        {
            return Err(QualifiedError::QualificationAuthenticationFailed);
        }
        if envelope.manifest_digest != manifest.manifest_digest {
            return Err(QualifiedError::QualificationManifestDigestMismatch);
        }
        if envelope.policy_generation != manifest.policy_generation {
            return Err(QualifiedError::QualificationGenerationMismatch);
        }
        if envelope.valid_from_sequence > envelope.expires_after_sequence
            || decision_sequence < envelope.valid_from_sequence
            || decision_sequence > envelope.expires_after_sequence
        {
            return Err(QualifiedError::QualificationExpired);
        }

        let signature_bytes = STANDARD
            .decode(&envelope.signature_base64)
            .map_err(|_| QualifiedError::QualificationSignatureMalformed)?;
        if signature_bytes.len() != 64 || STANDARD.encode(&signature_bytes) != envelope.signature_base64 {
            return Err(QualifiedError::QualificationSignatureMalformed);
        }
        let signature = Signature::from_slice(&signature_bytes)
            .map_err(|_| QualifiedError::QualificationSignatureMalformed)?;
        self.verifying_key
            .verify(&canonical_qualification_envelope_signing_bytes_v1(envelope), &signature)
            .map_err(|_| QualifiedError::QualificationSignatureInvalid)?;

        Ok(AuthenticatedQualificationV1 {
            manifest_digest: manifest.manifest_digest,
            authority_digest: manifest.authority_digest,
            policy_generation: manifest.policy_generation,
            signer_epoch: envelope.signer_epoch,
        })
    }
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
    InvalidTrustAnchor,
    QualificationAuthenticationFailed,
    QualificationSignatureMalformed,
    QualificationSignatureInvalid,
    QualificationExpired,
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
    fn from(value: CalibratedError) -> Self { Self::Calibrated(value) }
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

pub fn canonical_qualification_envelope_signing_bytes_v1(
    envelope: &SignedQualificationEnvelopeV1,
) -> Vec<u8> {
    let mut bytes = QUALIFICATION_SIGNATURE_DOMAIN.to_vec();
    let signer = envelope.signer_id.as_bytes();
    bytes.extend_from_slice(&u32::try_from(signer.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(signer);
    bytes.extend_from_slice(&envelope.signer_epoch.to_be_bytes());
    bytes.extend_from_slice(envelope.authority_digest.as_array());
    bytes.extend_from_slice(envelope.manifest_digest.as_array());
    bytes.extend_from_slice(&envelope.policy_generation.to_be_bytes());
    bytes.extend_from_slice(&envelope.valid_from_sequence.to_be_bytes());
    bytes.extend_from_slice(&envelope.expires_after_sequence.to_be_bytes());
    bytes
}

pub fn decide_qualified(
    request: QualifiedDecisionRequestV1,
    authenticated: &AuthenticatedQualificationV1,
) -> Result<CalibratedIntuitionReceiptV1, QualifiedError> {
    validate_qualification(&request, authenticated)?;
    decide_calibrated_v2(request.decision).map_err(Into::into)
}

fn validate_qualification(
    request: &QualifiedDecisionRequestV1,
    authenticated: &AuthenticatedQualificationV1,
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
    if authenticated.manifest_digest != qualification.manifest_digest
        || authenticated.authority_digest != qualification.authority_digest
    {
        return Err(QualifiedError::QualificationAuthenticationFailed);
    }
    if authenticated.policy_generation != decision.policy_generation {
        return Err(QualifiedError::QualificationGenerationMismatch);
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

    if decision.completeness.omitted_count_bound != 0 {
        return Err(QualifiedError::IncompleteCandidateSet);
    }

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
    use base64::Engine as _;
    use ed25519_dalek::{Signer as _, SigningKey};
    use crate::calibrated::{
        AssignmentModeV1, CalibratedActionCandidateV1, CalibrationArtifactV1,
        CandidateSetCompletenessBindingV1, OodArtifactV1, canonical_candidate_order_digest_v1,
        canonical_candidate_set_digest_v1,
    };
    use codex_hepta_types::{FixedQ32, StableId};

    fn digest(value: &str) -> Digest32 { Digest32::of_bytes(value.as_bytes()) }
    fn id(value: &str) -> StableId { StableId::new(value).expect("test id") }
    fn p(raw: u64) -> ProbabilityQ32 { ProbabilityQ32::from_raw(raw).expect("probability") }

    fn qualified() -> (QualifiedDecisionRequestV1, SignedQualificationEnvelopeV1, SigningKey) {
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
        let signing_key = SigningKey::from_bytes(&[7u8; 32]);
        let mut envelope = SignedQualificationEnvelopeV1 {
            signer_id: "qualification-test".to_string(), signer_epoch: 3,
            authority_digest: authority, manifest_digest: qualification.manifest_digest,
            policy_generation: 7, valid_from_sequence: 1, expires_after_sequence: 100,
            signature_base64: String::new(),
        };
        envelope.signature_base64 = STANDARD.encode(
            signing_key.sign(&canonical_qualification_envelope_signing_bytes_v1(&envelope)).to_bytes()
        );
        (QualifiedDecisionRequestV1 { decision, profile, qualification }, envelope, signing_key)
    }

    fn authenticate(
        request: &QualifiedDecisionRequestV1,
        envelope: &SignedQualificationEnvelopeV1,
        signing_key: &SigningKey,
    ) -> Result<AuthenticatedQualificationV1, QualifiedError> {
        PinnedQualificationVerifierV1::from_bytes(
            envelope.signer_id.clone(), envelope.signer_epoch, envelope.authority_digest,
            signing_key.verifying_key().to_bytes(),
        )?.verify(envelope, &request.qualification, request.decision.sequence)
    }

    #[test]
    fn qualified_path_requires_valid_pinned_signature() {
        let (request, envelope, signing_key) = qualified();
        let authenticated = authenticate(&request, &envelope, &signing_key).expect("signature");
        assert!(decide_qualified(request, &authenticated).is_ok());
    }

    #[test]
    fn qualified_path_rejects_incomplete_candidate_set_inside_intuition_crate() {
        let (mut request, envelope, signing_key) = qualified();
        let authenticated = authenticate(&request, &envelope, &signing_key).expect("signature");
        request.decision.completeness.omitted_count_bound = 1;
        assert_eq!(decide_qualified(request, &authenticated), Err(QualifiedError::IncompleteCandidateSet));
    }

    #[test]
    fn qualified_path_rejects_request_local_threshold_drift() {
        let (mut request, envelope, signing_key) = qualified();
        let authenticated = authenticate(&request, &envelope, &signing_key).expect("signature");
        request.decision.maximum_ece_ppm += 1;
        assert_eq!(decide_qualified(request, &authenticated), Err(QualifiedError::CanonicalProfileMismatch));
    }

    #[test]
    fn qualified_path_rejects_tampered_signature() {
        let (request, mut envelope, signing_key) = qualified();
        envelope.manifest_digest = digest("tampered-manifest");
        let verifier = PinnedQualificationVerifierV1::from_bytes(
            envelope.signer_id.clone(), envelope.signer_epoch, envelope.authority_digest,
            signing_key.verifying_key().to_bytes(),
        ).expect("verifier");
        assert_eq!(
            verifier.verify(&envelope, &request.qualification, request.decision.sequence),
            Err(QualifiedError::QualificationManifestDigestMismatch)
        );
    }
}

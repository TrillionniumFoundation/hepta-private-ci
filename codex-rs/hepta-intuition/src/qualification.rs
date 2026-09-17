//! Authenticated production qualification boundary for calibrated intuition.
//!
//! V1/V2 calibrated decisions intentionally preserve historical replay behavior.
//! This module adds the production-facing V3 boundary. A caller must provide an
//! independently pinned Ed25519 trust anchor for the *current* policy generation
//! and profile. The signed policy qualification binds the canonical policy
//! profile, calibration result, OOD result, frozen validation corpus and learned
//! scorer contract. A second signed artifact binds the exact decision state and
//! complete ordered candidate set. The candidate-set digest already commits the
//! learned utility/confidence/OOD outputs, so the completeness signer attests the
//! exact scored set under the pinned scorer contract.
//!
//! This crate still grants no dispatch, effect, promotion or release authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::Verifier as _;
use ed25519_dalek::VerifyingKey;

use crate::calibrated::CalibratedDecisionRequestV1;
use crate::calibrated::CalibratedError;
use crate::calibrated::CalibratedIntuitionReceiptV1;
use crate::calibrated::CalibrationArtifactV1;
use crate::calibrated::CandidateSetCompletenessBindingV1;
use crate::calibrated::OodArtifactV1;
use crate::calibrated::RiskClass;
use crate::calibrated::canonical_calibrated_request_digest_v1;
use crate::calibrated::decide_calibrated_v2;

const MAX_PPM: u32 = 1_000_000;
const MAX_QUALIFIED_CANDIDATES: u32 = 128;

/// Formal ownership and semantic contract for the learned scorer.
///
/// `codex-hepta-intuition` does not own model inference. The external scorer
/// owner produces the utility, calibrated-confidence and OOD values consumed by
/// the policy. Production qualification pins this contract and the exact model
/// artifact before a decision can be admitted.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearnedScorerContractV1 {
    pub owner_id: StableId,
    pub scorer_service_digest: Digest32,
    pub model_digest: Digest32,
    pub feature_schema_digest: Digest32,
    pub score_semantics_digest: Digest32,
    pub calibration_link_digest: Digest32,
    pub support_digest: Digest32,
}

/// Canonical thresholds and risk rules for one policy generation.
///
/// Request copies of these values are compatibility fields only. V3 accepts a
/// request only when they exactly match this signed profile, and then executes
/// with these profile values as the source of truth.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalPolicyProfileV1 {
    pub policy_digest: Digest32,
    pub objective_class_digest: Digest32,
    pub generation: u64,
    pub minimum_confidence: ProbabilityQ32,
    pub maximum_ece_ppm: u32,
    pub maximum_ood_false_acceptance_ppm: u32,
    pub allow_elevated_risk_direct: bool,
    pub high_risk_forces_slow_path: bool,
    pub scorer: LearnedScorerContractV1,
}

/// Signed, current-generation qualification of a policy profile against frozen
/// validation data.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedPolicyQualificationV1 {
    pub issuer_id: StableId,
    pub issuer_epoch: u64,
    pub profile: CanonicalPolicyProfileV1,
    pub calibration: CalibrationArtifactV1,
    pub ood: OodArtifactV1,
    pub frozen_validation_data_digest: Digest32,
    pub qualification_report_digest: Digest32,
    pub valid_from_sequence: u64,
    pub expires_after_sequence: u64,
    pub signature: [u8; 64],
}

/// Signed per-decision attestation of the complete, ordered, scored candidate
/// set. The payload binds the current profile and scorer contract so a receipt
/// from another model, generation or feature schema cannot be replayed.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedCandidateCompletenessV1 {
    pub issuer_id: StableId,
    pub issuer_epoch: u64,
    pub decision_id: StableId,
    pub objective_digest: Digest32,
    pub objective_class_digest: Digest32,
    pub state_digest: Digest32,
    pub policy_digest: Digest32,
    pub policy_generation: u64,
    pub sequence: u64,
    pub policy_profile_digest: Digest32,
    pub scorer_contract_digest: Digest32,
    pub completeness: CandidateSetCompletenessBindingV1,
    pub signature: [u8; 64],
}

/// Receipt emitted only after both signed qualification layers are verified.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualifiedIntuitionReceiptV3 {
    pub decision: CalibratedIntuitionReceiptV1,
    pub request_digest: Digest32,
    pub policy_profile_digest: Digest32,
    pub scorer_contract_digest: Digest32,
    pub policy_qualification_digest: Digest32,
    pub completeness_artifact_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

/// Independent trust anchor. None of these values are learned from a signed
/// artifact. The host must provision them from its deployment/qualification
/// authority store.
#[derive(Clone)]
pub struct QualificationVerifierV1 {
    issuer_id: StableId,
    issuer_epoch: u64,
    verifying_key: VerifyingKey,
    current_policy_digest: Digest32,
    current_policy_generation: u64,
    current_profile_digest: Digest32,
}

impl QualificationVerifierV1 {
    pub fn new(
        issuer_id: StableId,
        issuer_epoch: u64,
        verifying_key: VerifyingKey,
        current_policy_digest: Digest32,
        current_policy_generation: u64,
        current_profile_digest: Digest32,
    ) -> Result<Self, QualificationError> {
        if issuer_epoch == 0
            || verifying_key.is_weak()
            || current_policy_digest.is_zero()
            || current_profile_digest.is_zero()
        {
            return Err(QualificationError::InvalidTrustAnchor);
        }
        Ok(Self {
            issuer_id,
            issuer_epoch,
            verifying_key,
            current_policy_digest,
            current_policy_generation,
            current_profile_digest,
        })
    }

    pub fn from_bytes(
        issuer_id: StableId,
        issuer_epoch: u64,
        public_key: [u8; 32],
        current_policy_digest: Digest32,
        current_policy_generation: u64,
        current_profile_digest: Digest32,
    ) -> Result<Self, QualificationError> {
        let verifying_key = VerifyingKey::from_bytes(&public_key)
            .map_err(|_| QualificationError::InvalidTrustAnchor)?;
        Self::new(
            issuer_id,
            issuer_epoch,
            verifying_key,
            current_policy_digest,
            current_policy_generation,
            current_profile_digest,
        )
    }

    pub fn verify_policy_qualification(
        &self,
        artifact: &SignedPolicyQualificationV1,
        sequence: u64,
    ) -> Result<(), QualificationError> {
        validate_policy_qualification_shape(artifact)?;
        self.verify_issuer(&artifact.issuer_id, artifact.issuer_epoch)?;
        if artifact.profile.policy_digest != self.current_policy_digest
            || artifact.profile.generation != self.current_policy_generation
        {
            return Err(QualificationError::CurrentGenerationMismatch);
        }
        let profile_digest = canonical_policy_profile_digest_v1(&artifact.profile)?;
        if profile_digest != self.current_profile_digest {
            return Err(QualificationError::CurrentProfileMismatch);
        }
        let digest = canonical_policy_qualification_digest_v1(artifact)?;
        self.verify_signature(digest, &artifact.signature)?;
        if sequence < artifact.valid_from_sequence || sequence > artifact.expires_after_sequence {
            return Err(QualificationError::QualificationExpired);
        }
        Ok(())
    }

    pub fn verify_candidate_completeness(
        &self,
        artifact: &SignedCandidateCompletenessV1,
    ) -> Result<(), QualificationError> {
        validate_candidate_completeness_shape(artifact)?;
        self.verify_issuer(&artifact.issuer_id, artifact.issuer_epoch)?;
        if artifact.policy_digest != self.current_policy_digest
            || artifact.policy_generation != self.current_policy_generation
        {
            return Err(QualificationError::CurrentGenerationMismatch);
        }
        if artifact.policy_profile_digest != self.current_profile_digest {
            return Err(QualificationError::CurrentProfileMismatch);
        }
        let digest = canonical_candidate_completeness_digest_v1(artifact)?;
        if artifact.completeness.receipt_digest != digest {
            return Err(QualificationError::CompletenessDigestMismatch);
        }
        self.verify_signature(digest, &artifact.signature)
    }

    fn verify_issuer(
        &self,
        issuer_id: &StableId,
        issuer_epoch: u64,
    ) -> Result<(), QualificationError> {
        if issuer_id != &self.issuer_id {
            return Err(QualificationError::IssuerMismatch);
        }
        if issuer_epoch != self.issuer_epoch {
            return Err(QualificationError::IssuerEpochMismatch);
        }
        Ok(())
    }

    fn verify_signature(
        &self,
        digest: Digest32,
        signature_bytes: &[u8; 64],
    ) -> Result<(), QualificationError> {
        let signature = Signature::from_slice(signature_bytes)
            .map_err(|_| QualificationError::SignatureMalformed)?;
        self.verifying_key
            .verify(digest.as_array(), &signature)
            .map_err(|_| QualificationError::SignatureInvalid)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum QualificationError {
    Calibrated(CalibratedError),
    Arithmetic,
    EmptyDigest(&'static str),
    InvalidTrustAnchor,
    InvalidMetric,
    InvalidRiskProfile,
    QualificationWindowInvalid,
    QualificationExpired,
    IssuerMismatch,
    IssuerEpochMismatch,
    SignatureMalformed,
    SignatureInvalid,
    CurrentGenerationMismatch,
    CurrentProfileMismatch,
    PolicyBindingMismatch,
    ObjectiveBindingMismatch,
    ScorerContractMismatch,
    CalibrationDigestMismatch,
    OodDigestMismatch,
    ArtifactBindingMismatch,
    CompletenessDigestMismatch,
    CompletenessBindingMismatch,
    IncompleteCandidateSet,
    PolicyProfileMismatch,
}

impl fmt::Display for QualificationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for QualificationError {}

impl From<CalibratedError> for QualificationError {
    fn from(value: CalibratedError) -> Self {
        Self::Calibrated(value)
    }
}

/// Production-facing decision entrypoint.
///
/// Thresholds, risk rules, calibration, OOD qualification, scorer ownership,
/// model identity and candidate completeness all come from authenticated data.
/// Caller-supplied compatibility copies must match but never select the active
/// profile.
pub fn decide_qualified_v3(
    request: CalibratedDecisionRequestV1,
    qualification: &SignedPolicyQualificationV1,
    completeness: &SignedCandidateCompletenessV1,
    verifier: &QualificationVerifierV1,
) -> Result<QualifiedIntuitionReceiptV3, QualificationError> {
    verifier.verify_policy_qualification(qualification, request.sequence)?;
    verifier.verify_candidate_completeness(completeness)?;

    let profile = &qualification.profile;
    let profile_digest = canonical_policy_profile_digest_v1(profile)?;
    let scorer_contract_digest = canonical_scorer_contract_digest_v1(&profile.scorer)?;

    if request.policy_digest != profile.policy_digest
        || request.policy_generation != profile.generation
        || completeness.policy_digest != request.policy_digest
        || completeness.policy_generation != request.policy_generation
    {
        return Err(QualificationError::PolicyBindingMismatch);
    }
    if request.objective_class_digest != profile.objective_class_digest
        || completeness.objective_digest != request.objective_digest
        || completeness.objective_class_digest != request.objective_class_digest
        || completeness.state_digest != request.state_digest
        || completeness.decision_id != request.decision_id
        || completeness.sequence != request.sequence
    {
        return Err(QualificationError::ObjectiveBindingMismatch);
    }
    if completeness.policy_profile_digest != profile_digest
        || completeness.scorer_contract_digest != scorer_contract_digest
    {
        return Err(QualificationError::ScorerContractMismatch);
    }
    if request.minimum_confidence != profile.minimum_confidence
        || request.maximum_ece_ppm != profile.maximum_ece_ppm
        || request.maximum_ood_false_acceptance_ppm
            != profile.maximum_ood_false_acceptance_ppm
    {
        return Err(QualificationError::PolicyProfileMismatch);
    }
    if request.calibration != qualification.calibration || request.ood != qualification.ood {
        return Err(QualificationError::ArtifactBindingMismatch);
    }
    if request.completeness != completeness.completeness {
        return Err(QualificationError::CompletenessBindingMismatch);
    }
    if request.completeness.omitted_count_bound != 0 {
        return Err(QualificationError::IncompleteCandidateSet);
    }

    // Execute from the authenticated profile. Mirrored request fields have
    // already been checked only to fail closed on incompatible callers.
    let mut effective = request.clone();
    effective.minimum_confidence = profile.minimum_confidence;
    effective.maximum_ece_ppm = profile.maximum_ece_ppm;
    effective.maximum_ood_false_acceptance_ppm = profile.maximum_ood_false_acceptance_ppm;
    effective.calibration = qualification.calibration.clone();
    effective.ood = qualification.ood.clone();
    if matches!(request.risk_class, RiskClass::High)
        || (matches!(request.risk_class, RiskClass::Elevated)
            && !profile.allow_elevated_risk_direct)
    {
        effective.risk_class = RiskClass::High;
    }

    let decision = decide_calibrated_v2(effective)?;
    let request_digest = canonical_calibrated_request_digest_v1(&request)?;
    let policy_qualification_digest = canonical_policy_qualification_digest_v1(qualification)?;
    let completeness_artifact_digest = canonical_candidate_completeness_digest_v1(completeness)?;
    let mut bytes = b"hepta.intuition.qualified-decision.v3".to_vec();
    for digest in [
        request_digest,
        profile_digest,
        scorer_contract_digest,
        policy_qualification_digest,
        completeness_artifact_digest,
        decision.receipt_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    let receipt_digest = Digest32::of_bytes(&bytes);

    Ok(QualifiedIntuitionReceiptV3 {
        decision,
        request_digest,
        policy_profile_digest: profile_digest,
        scorer_contract_digest,
        policy_qualification_digest,
        completeness_artifact_digest,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn canonical_calibration_artifact_digest_v1(
    artifact: &CalibrationArtifactV1,
) -> Result<Digest32, QualificationError> {
    let mut bytes = b"hepta.intuition.calibration-artifact.v1".to_vec();
    bytes.extend_from_slice(artifact.policy_digest.as_array());
    bytes.extend_from_slice(artifact.objective_class_digest.as_array());
    bytes.extend_from_slice(&artifact.generation.to_be_bytes());
    bytes.extend_from_slice(&artifact.valid_from_sequence.to_be_bytes());
    bytes.extend_from_slice(&artifact.expires_after_sequence.to_be_bytes());
    bytes.extend_from_slice(&artifact.measured_ece_ppm.to_be_bytes());
    bytes.extend_from_slice(artifact.subgroup_audit_digest.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

pub fn canonical_ood_artifact_digest_v1(
    artifact: &OodArtifactV1,
) -> Result<Digest32, QualificationError> {
    let mut bytes = b"hepta.intuition.ood-artifact.v1".to_vec();
    bytes.extend_from_slice(artifact.policy_digest.as_array());
    bytes.extend_from_slice(artifact.detector_digest.as_array());
    bytes.extend_from_slice(artifact.support_digest.as_array());
    bytes.extend_from_slice(&artifact.generation.to_be_bytes());
    bytes.extend_from_slice(&artifact.valid_from_sequence.to_be_bytes());
    bytes.extend_from_slice(&artifact.expires_after_sequence.to_be_bytes());
    bytes.extend_from_slice(&artifact.maximum_in_domain_score.raw().to_be_bytes());
    bytes.extend_from_slice(&artifact.measured_false_acceptance_ppm.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

pub fn canonical_scorer_contract_digest_v1(
    contract: &LearnedScorerContractV1,
) -> Result<Digest32, QualificationError> {
    let mut bytes = b"hepta.intuition.learned-scorer-contract.v1".to_vec();
    push_id(&mut bytes, &contract.owner_id)?;
    for digest in [
        contract.scorer_service_digest,
        contract.model_digest,
        contract.feature_schema_digest,
        contract.score_semantics_digest,
        contract.calibration_link_digest,
        contract.support_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub fn canonical_policy_profile_digest_v1(
    profile: &CanonicalPolicyProfileV1,
) -> Result<Digest32, QualificationError> {
    let mut bytes = b"hepta.intuition.policy-profile.v1".to_vec();
    bytes.extend_from_slice(profile.policy_digest.as_array());
    bytes.extend_from_slice(profile.objective_class_digest.as_array());
    bytes.extend_from_slice(&profile.generation.to_be_bytes());
    bytes.extend_from_slice(&profile.minimum_confidence.raw().to_be_bytes());
    bytes.extend_from_slice(&profile.maximum_ece_ppm.to_be_bytes());
    bytes.extend_from_slice(&profile.maximum_ood_false_acceptance_ppm.to_be_bytes());
    bytes.push(u8::from(profile.allow_elevated_risk_direct));
    bytes.push(u8::from(profile.high_risk_forces_slow_path));
    bytes.extend_from_slice(canonical_scorer_contract_digest_v1(&profile.scorer)?.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

pub fn canonical_policy_qualification_digest_v1(
    artifact: &SignedPolicyQualificationV1,
) -> Result<Digest32, QualificationError> {
    let mut bytes = b"hepta.intuition.signed-policy-qualification.v1".to_vec();
    push_id(&mut bytes, &artifact.issuer_id)?;
    bytes.extend_from_slice(&artifact.issuer_epoch.to_be_bytes());
    bytes.extend_from_slice(canonical_policy_profile_digest_v1(&artifact.profile)?.as_array());
    bytes.extend_from_slice(canonical_calibration_artifact_digest_v1(&artifact.calibration)?.as_array());
    bytes.extend_from_slice(canonical_ood_artifact_digest_v1(&artifact.ood)?.as_array());
    bytes.extend_from_slice(artifact.frozen_validation_data_digest.as_array());
    bytes.extend_from_slice(artifact.qualification_report_digest.as_array());
    bytes.extend_from_slice(&artifact.valid_from_sequence.to_be_bytes());
    bytes.extend_from_slice(&artifact.expires_after_sequence.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

pub fn canonical_candidate_completeness_digest_v1(
    artifact: &SignedCandidateCompletenessV1,
) -> Result<Digest32, QualificationError> {
    let mut bytes = b"hepta.intuition.signed-candidate-completeness.v1".to_vec();
    push_id(&mut bytes, &artifact.issuer_id)?;
    bytes.extend_from_slice(&artifact.issuer_epoch.to_be_bytes());
    push_id(&mut bytes, &artifact.decision_id)?;
    for digest in [
        artifact.objective_digest,
        artifact.objective_class_digest,
        artifact.state_digest,
        artifact.policy_digest,
        artifact.policy_profile_digest,
        artifact.scorer_contract_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&artifact.policy_generation.to_be_bytes());
    bytes.extend_from_slice(&artifact.sequence.to_be_bytes());
    let completeness = &artifact.completeness;
    for digest in [
        completeness.generator_digest,
        completeness.grammar_digest,
        completeness.hard_filter_digest,
        completeness.truncation_digest,
        completeness.candidate_set_digest,
        completeness.canonical_order_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&completeness.candidate_count.to_be_bytes());
    bytes.extend_from_slice(&completeness.omitted_count_bound.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn validate_policy_qualification_shape(
    artifact: &SignedPolicyQualificationV1,
) -> Result<(), QualificationError> {
    let profile = &artifact.profile;
    if profile.maximum_ece_ppm > MAX_PPM
        || profile.maximum_ood_false_acceptance_ppm > MAX_PPM
        || artifact.calibration.measured_ece_ppm > MAX_PPM
        || artifact.ood.measured_false_acceptance_ppm > MAX_PPM
    {
        return Err(QualificationError::InvalidMetric);
    }
    if !profile.high_risk_forces_slow_path {
        return Err(QualificationError::InvalidRiskProfile);
    }
    for (label, digest) in [
        ("policy", profile.policy_digest),
        ("objective class", profile.objective_class_digest),
        ("frozen validation data", artifact.frozen_validation_data_digest),
        ("qualification report", artifact.qualification_report_digest),
        ("scorer service", profile.scorer.scorer_service_digest),
        ("model", profile.scorer.model_digest),
        ("feature schema", profile.scorer.feature_schema_digest),
        ("score semantics", profile.scorer.score_semantics_digest),
        ("calibration link", profile.scorer.calibration_link_digest),
        ("scorer support", profile.scorer.support_digest),
    ] {
        if digest.is_zero() {
            return Err(QualificationError::EmptyDigest(label));
        }
    }
    if artifact.valid_from_sequence > artifact.expires_after_sequence
        || artifact.calibration.valid_from_sequence > artifact.calibration.expires_after_sequence
        || artifact.ood.valid_from_sequence > artifact.ood.expires_after_sequence
    {
        return Err(QualificationError::QualificationWindowInvalid);
    }
    if artifact.valid_from_sequence < artifact.calibration.valid_from_sequence
        || artifact.expires_after_sequence > artifact.calibration.expires_after_sequence
        || artifact.valid_from_sequence < artifact.ood.valid_from_sequence
        || artifact.expires_after_sequence > artifact.ood.expires_after_sequence
    {
        return Err(QualificationError::QualificationWindowInvalid);
    }
    if artifact.calibration.policy_digest != profile.policy_digest
        || artifact.ood.policy_digest != profile.policy_digest
    {
        return Err(QualificationError::PolicyBindingMismatch);
    }
    if artifact.calibration.objective_class_digest != profile.objective_class_digest {
        return Err(QualificationError::ObjectiveBindingMismatch);
    }
    if artifact.calibration.generation != profile.generation
        || artifact.ood.generation != profile.generation
    {
        return Err(QualificationError::CurrentGenerationMismatch);
    }
    let calibration_digest = canonical_calibration_artifact_digest_v1(&artifact.calibration)?;
    if artifact.calibration.artifact_digest != calibration_digest {
        return Err(QualificationError::CalibrationDigestMismatch);
    }
    let ood_digest = canonical_ood_artifact_digest_v1(&artifact.ood)?;
    if artifact.ood.artifact_digest != ood_digest {
        return Err(QualificationError::OodDigestMismatch);
    }
    if profile.scorer.calibration_link_digest != calibration_digest
        || profile.scorer.support_digest != artifact.ood.support_digest
    {
        return Err(QualificationError::ScorerContractMismatch);
    }
    if artifact.calibration.measured_ece_ppm > profile.maximum_ece_ppm
        || artifact.ood.measured_false_acceptance_ppm
            > profile.maximum_ood_false_acceptance_ppm
    {
        return Err(QualificationError::ArtifactBindingMismatch);
    }
    Ok(())
}

fn validate_candidate_completeness_shape(
    artifact: &SignedCandidateCompletenessV1,
) -> Result<(), QualificationError> {
    if artifact.completeness.omitted_count_bound != 0 {
        return Err(QualificationError::IncompleteCandidateSet);
    }
    if artifact.completeness.candidate_count == 0
        || artifact.completeness.candidate_count > MAX_QUALIFIED_CANDIDATES
    {
        return Err(QualificationError::CompletenessBindingMismatch);
    }
    for (label, digest) in [
        ("objective", artifact.objective_digest),
        ("objective class", artifact.objective_class_digest),
        ("state", artifact.state_digest),
        ("policy", artifact.policy_digest),
        ("policy profile", artifact.policy_profile_digest),
        ("scorer contract", artifact.scorer_contract_digest),
        ("completeness receipt", artifact.completeness.receipt_digest),
        ("generator", artifact.completeness.generator_digest),
        ("grammar", artifact.completeness.grammar_digest),
        ("hard filter", artifact.completeness.hard_filter_digest),
        ("truncation", artifact.completeness.truncation_digest),
        ("candidate set", artifact.completeness.candidate_set_digest),
        ("candidate order", artifact.completeness.canonical_order_digest),
    ] {
        if digest.is_zero() {
            return Err(QualificationError::EmptyDigest(label));
        }
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), QualificationError> {
    let raw = value.as_str().as_bytes();
    let len = u32::try_from(raw.len()).map_err(|_| QualificationError::Arithmetic)?;
    bytes.extend_from_slice(&len.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

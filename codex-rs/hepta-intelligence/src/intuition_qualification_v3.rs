//! Current authenticated intuition admission.
//!
//! This is the product-facing bridge from independently signed generator,
//! evaluator and observer evidence to the production policy contract.  The
//! observer signs the split V2 runtime commitment; no V1 scoring commitment can
//! reach this entrypoint.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_intuition::AssignmentCommitmentV2;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CanonicalPolicyProfileV1;
use codex_hepta_intuition::ProductionIntuitionReceiptV1;
use codex_hepta_intuition::ProductionPolicyError;
use codex_hepta_intuition::ScoringCommitmentV2;
use codex_hepta_intuition::canonical_assignment_commitment_digest_v2;
use codex_hepta_intuition::canonical_completeness_evidence_payload_v1;
use codex_hepta_intuition::canonical_policy_profile_digest_v1;
use codex_hepta_intuition::canonical_profile_qualification_payload_v1;
use codex_hepta_intuition::canonical_runtime_commitment_payload_v2;
use codex_hepta_intuition::canonical_scoring_commitment_digest_v2;
use codex_hepta_intuition::decide_calibrated_v4;
use codex_hepta_learning_ledger::CausalV2Error;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::verify_independent_roles;
use codex_hepta_learning_ledger::verify_signed_role_separation;
use codex_hepta_types::Digest32;

use crate::IntuitionQualificationEvidenceV2;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedIntuitionDecisionV3 {
    pub decision: ProductionIntuitionReceiptV1,
    pub profile_digest: Digest32,
    pub scoring_commitment_digest: Digest32,
    pub assignment_commitment_digest: Digest32,
    pub trust_digest: Digest32,
    pub completeness_payload_digest: Digest32,
    pub profile_qualification_payload_digest: Digest32,
    pub runtime_payload_digest: Digest32,
    pub authentication_digest: Digest32,
}

#[derive(Debug)]
pub enum IntuitionQualificationErrorV3 {
    Evidence(SignedEvidenceError),
    Independence(CausalV2Error),
    Policy(ProductionPolicyError),
}

impl IntuitionQualificationErrorV3 {
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::Evidence(_) => "intuition.qualification.v3.evidence_rejected",
            Self::Independence(_) => "intuition.qualification.v3.role_separation_rejected",
            Self::Policy(source) => source.code(),
        }
    }
}

impl fmt::Display for IntuitionQualificationErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code())
    }
}

impl StdError for IntuitionQualificationErrorV3 {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Evidence(source) => Some(source),
            Self::Independence(source) => Some(source),
            Self::Policy(source) => Some(source),
        }
    }
}

impl From<SignedEvidenceError> for IntuitionQualificationErrorV3 {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Evidence(value)
    }
}

impl From<CausalV2Error> for IntuitionQualificationErrorV3 {
    fn from(value: CausalV2Error) -> Self {
        Self::Independence(value)
    }
}

impl From<ProductionPolicyError> for IntuitionQualificationErrorV3 {
    fn from(value: ProductionPolicyError) -> Self {
        Self::Policy(value)
    }
}

/// Verify independent Generator/Evaluator/Observer evidence and admit the
/// decision through the current production policy contract.
pub fn decide_authenticated_intuition_v3(
    request: CalibratedDecisionRequestV1,
    profile: CanonicalPolicyProfileV1,
    scoring: ScoringCommitmentV2,
    assignment: AssignmentCommitmentV2,
    evidence: IntuitionQualificationEvidenceV2<'_>,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<AuthenticatedIntuitionDecisionV3, IntuitionQualificationErrorV3> {
    let completeness_payload = canonical_completeness_evidence_payload_v1(&request)
        .map_err(|source| ProductionPolicyError::Qualified(source.into()))?;
    let profile_qualification_payload = canonical_profile_qualification_payload_v1(&profile)
        .map_err(|source| match source {
            codex_hepta_intuition::RuntimeCommitmentError::Profile(inner) => {
                ProductionPolicyError::Qualified(inner)
            }
            _ => ProductionPolicyError::ScoringIdentityMismatch("profile qualification"),
        })?;
    let runtime_payload =
        canonical_runtime_commitment_payload_v2(&request, &profile, &scoring, &assignment)?;

    let generator = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        evidence.completeness,
        &completeness_payload,
        now,
    )?;
    let evaluator = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        evidence.profile_qualification,
        &profile_qualification_payload,
        now,
    )?;
    let observer = verifier.verify(
        LearningEvidenceRoleV1::Observer,
        evidence.runtime,
        &runtime_payload,
        now,
    )?;

    verify_signed_role_separation(&generator, &evaluator, now)?;
    verify_signed_role_separation(&generator, &observer, now)?;
    verify_independent_roles(evaluator.principal(), observer.principal(), now)?;

    let profile_digest =
        canonical_policy_profile_digest_v1(&profile).map_err(ProductionPolicyError::Qualified)?;
    let scoring_commitment_digest = canonical_scoring_commitment_digest_v2(&scoring)?;
    let assignment_commitment_digest =
        canonical_assignment_commitment_digest_v2(&request, &assignment)?;
    let decision = decide_calibrated_v4(request, &profile)?;
    let completeness_payload_digest = Digest32::of_bytes(&completeness_payload);
    let profile_qualification_payload_digest = Digest32::of_bytes(&profile_qualification_payload);
    let runtime_payload_digest = Digest32::of_bytes(&runtime_payload);

    let mut bytes = b"hepta.intelligence.authenticated-intuition.v3\0".to_vec();
    for digest in [
        verifier.trust_digest(),
        profile_digest,
        scoring_commitment_digest,
        assignment_commitment_digest,
        completeness_payload_digest,
        profile_qualification_payload_digest,
        runtime_payload_digest,
        Digest32::of_bytes(&evidence.completeness.signing_bytes()),
        Digest32::of_bytes(&evidence.profile_qualification.signing_bytes()),
        Digest32::of_bytes(&evidence.runtime.signing_bytes()),
        decision.receipt_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&evidence.completeness.signature);
    bytes.extend_from_slice(&evidence.profile_qualification.signature);
    bytes.extend_from_slice(&evidence.runtime.signature);

    Ok(AuthenticatedIntuitionDecisionV3 {
        decision,
        profile_digest,
        scoring_commitment_digest,
        assignment_commitment_digest,
        trust_digest: verifier.trust_digest(),
        completeness_payload_digest,
        profile_qualification_payload_digest,
        runtime_payload_digest,
        authentication_digest: Digest32::of_bytes(&bytes),
    })
}

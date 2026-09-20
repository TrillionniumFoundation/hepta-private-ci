//! Authenticated admission for operator applicability and regularity.
//!
//! Structural V1 validators remain pure compatibility surfaces. Qualification
//! code should use these V2 entry points so the exact structural receipt is
//! attested by a host-trusted evaluator that is independent from the generator.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_role_separation;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::OperatorApplicabilityCertificateV1;
use crate::OperatorClosureError;
use crate::OperatorRegularityAdmissionV1;
use crate::OperatorRegularityAssessmentV1;
use crate::admit_operator_regularity;
use crate::validate_applicability_certificate;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedOperatorEvidenceV2 {
    pub generator: SignedLearningEvidenceV1,
    pub evaluator: SignedLearningEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedApplicabilityAdmissionV2 {
    pub certificate_digest: Digest32,
    pub trust_digest: Digest32,
    pub authentication_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedOperatorRegularityAdmissionV2 {
    pub admission: OperatorRegularityAdmissionV1,
    pub trust_digest: Digest32,
    pub authentication_digest: Digest32,
}

pub fn validate_applicability_with_signed_evidence_v2(
    certificate: &OperatorApplicabilityCertificateV1,
    evidence: &SignedOperatorEvidenceV2,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<AuthenticatedApplicabilityAdmissionV2, AuthenticatedOperatorError> {
    let certificate_digest = validate_applicability_certificate(certificate, now)?;
    let authentication_digest = authenticate_pair(
        verifier,
        evidence,
        certificate_digest.as_array(),
        &certificate.evaluator_id,
        certificate.evaluator_credential_digest,
        now,
    )?;
    Ok(AuthenticatedApplicabilityAdmissionV2 {
        certificate_digest,
        trust_digest: verifier.trust_digest(),
        authentication_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn admit_operator_regularity_with_signed_evidence_v2(
    assessment: OperatorRegularityAssessmentV1,
    evidence: &SignedOperatorEvidenceV2,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<AuthenticatedOperatorRegularityAdmissionV2, AuthenticatedOperatorError> {
    let evaluator_id = assessment.evaluator_id.clone();
    let evaluator_credential_digest = assessment.evaluator_credential_digest;
    let admission = admit_operator_regularity(assessment)?;
    let authentication_digest = authenticate_pair(
        verifier,
        evidence,
        admission.assessment_digest.as_array(),
        &evaluator_id,
        evaluator_credential_digest,
        now,
    )?;
    Ok(AuthenticatedOperatorRegularityAdmissionV2 {
        admission,
        trust_digest: verifier.trust_digest(),
        authentication_digest,
    })
}

fn authenticate_pair(
    verifier: &LearningEvidenceVerifierV1,
    evidence: &SignedOperatorEvidenceV2,
    payload: &[u8],
    evaluator_id: &StableId,
    evaluator_credential_digest: Digest32,
    now: u64,
) -> Result<Digest32, AuthenticatedOperatorError> {
    let generator = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &evidence.generator,
        payload,
        now,
    )?;
    let evaluator = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        &evidence.evaluator,
        payload,
        now,
    )?;
    if evaluator.principal().principal_id != *evaluator_id
        || evaluator.principal().credential_chain_digest != evaluator_credential_digest
    {
        return Err(AuthenticatedOperatorError::IdentityBinding);
    }
    verify_signed_role_separation(&generator, &evaluator, now)?;

    let mut bytes = b"hepta.bellman-operator.authenticated-evidence.v2".to_vec();
    bytes.extend_from_slice(verifier.trust_digest().as_array());
    bytes.extend_from_slice(payload);
    for signed in [&evidence.generator, &evidence.evaluator] {
        bytes.extend_from_slice(Digest32::of_bytes(&signed.signing_bytes()).as_array());
        bytes.extend_from_slice(&signed.signature);
    }
    Ok(Digest32::of_bytes(&bytes))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AuthenticatedOperatorError {
    Operator(OperatorClosureError),
    Evidence(SignedEvidenceError),
    IdentityBinding,
}

impl fmt::Display for AuthenticatedOperatorError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AuthenticatedOperatorError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Operator(error) => Some(error),
            Self::Evidence(error) => Some(error),
            Self::IdentityBinding => None,
        }
    }
}

impl From<OperatorClosureError> for AuthenticatedOperatorError {
    fn from(value: OperatorClosureError) -> Self {
        Self::Operator(value)
    }
}

impl From<SignedEvidenceError> for AuthenticatedOperatorError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Evidence(value)
    }
}

#[cfg(test)]
#[path = "authenticated_tests.rs"]
mod tests;

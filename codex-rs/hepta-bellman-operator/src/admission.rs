//! Authenticated and dataset-bound admission for operator training.
//!
//! The pure V1 kernels remain available for deterministic fixtures and legacy
//! callers. Product and qualification integrations should use these wrappers:
//! they bind training rows to a self-verifying frozen dataset receipt and bind
//! applicability/regularity claims to cryptographically admitted evaluator
//! evidence that is independent from the generator.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::DatasetReceiptError;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_dataset_snapshot_receipt_v3;
use codex_hepta_learning_ledger::verify_signed_role_separation;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::LearnedOperatorError;
use crate::OperatorApplicabilityCertificateV1;
use crate::OperatorClosureError;
use crate::OperatorRegularityAdmissionV1;
use crate::OperatorRegularityAssessmentV1;
use crate::TabularOperatorArtifactV1;
use crate::TabularOperatorPlanV1;
use crate::TabularWorldModelV1;
use crate::WorldModelError;
use crate::WorldModelSampleV1;
use crate::admit_operator_regularity;
use crate::fit_tabular_operator;
use crate::fit_transition_model;
use crate::validate_applicability_certificate;

/// Validate structural applicability and require a host-authenticated evaluator
/// attestation that is independent from the generator.
///
/// The evaluator signs the 32-byte structural receipt digest returned by
/// `validate_applicability_certificate`. The signature/trust verification is
/// performed by `LearningEvidenceVerifierV1` before this function is called.
pub fn validate_applicability_certificate_authenticated(
    certificate: &OperatorApplicabilityCertificateV1,
    generator: &VerifiedLearningEvidenceV1,
    evaluator: &VerifiedLearningEvidenceV1,
    now: u64,
) -> Result<Digest32, OperatorAdmissionError> {
    let receipt_digest = validate_applicability_certificate(certificate, now)?;
    require_authenticated_evaluator(
        &certificate.evaluator_id,
        certificate.evaluator_credential_digest,
        receipt_digest,
        generator,
        evaluator,
        now,
    )?;
    Ok(receipt_digest)
}

/// Admit regularity only when the assessment is bound to independently
/// authenticated evaluator evidence. The evaluator signs the 32-byte
/// `assessment_digest` pre-admission receipt.
pub fn admit_operator_regularity_authenticated(
    assessment: OperatorRegularityAssessmentV1,
    generator: &VerifiedLearningEvidenceV1,
    evaluator: &VerifiedLearningEvidenceV1,
    now: u64,
) -> Result<OperatorRegularityAdmissionV1, OperatorAdmissionError> {
    let evaluator_id = assessment.evaluator_id.clone();
    let evaluator_credential_digest = assessment.evaluator_credential_digest;
    let admission = admit_operator_regularity(assessment)?;
    require_authenticated_evaluator(
        &evaluator_id,
        evaluator_credential_digest,
        admission.assessment_digest,
        generator,
        evaluator,
        now,
    )?;
    Ok(admission)
}

/// Fit the tabular operator only from rows directly named by a verified frozen
/// dataset receipt. Each sample's `evidence_digest` must be one of the receipt's
/// canonical source-record digests.
pub fn fit_tabular_operator_from_dataset_receipt(
    plan: TabularOperatorPlanV1,
    receipt: &DatasetSnapshotReceiptV3,
    now: u64,
) -> Result<TabularOperatorArtifactV1, OperatorAdmissionError> {
    verify_dataset_snapshot_receipt_v3(receipt, now)?;
    if plan.dataset_digest != receipt.snapshot.dataset_digest
        || plan.objective_digest != receipt.snapshot.objective_digest
    {
        return Err(OperatorAdmissionError::DatasetBinding);
    }
    require_receipt_rows(
        receipt,
        plan.samples.iter().map(|sample| sample.evidence_digest),
    )?;
    Ok(fit_tabular_operator(plan)?)
}

/// Fit the action-conditioned world model from a verified frozen dataset
/// receipt. The dataset digest is taken from the receipt rather than supplied
/// independently by the caller.
pub fn fit_transition_model_from_dataset_receipt(
    model_id: StableId,
    receipt: &DatasetSnapshotReceiptV3,
    samples: Vec<WorldModelSampleV1>,
    now: u64,
) -> Result<TabularWorldModelV1, OperatorAdmissionError> {
    verify_dataset_snapshot_receipt_v3(receipt, now)?;
    require_receipt_rows(receipt, samples.iter().map(|sample| sample.evidence_digest))?;
    Ok(fit_transition_model(
        model_id,
        receipt.snapshot.dataset_digest,
        samples,
    )?)
}

fn require_receipt_rows(
    receipt: &DatasetSnapshotReceiptV3,
    evidence: impl IntoIterator<Item = Digest32>,
) -> Result<(), OperatorAdmissionError> {
    for digest in evidence {
        if receipt
            .snapshot
            .source_record_digests
            .binary_search(&digest)
            .is_err()
        {
            return Err(OperatorAdmissionError::EvidenceOutsideDataset);
        }
    }
    Ok(())
}

fn require_authenticated_evaluator(
    evaluator_id: &StableId,
    evaluator_credential_digest: Digest32,
    structural_receipt_digest: Digest32,
    generator: &VerifiedLearningEvidenceV1,
    evaluator: &VerifiedLearningEvidenceV1,
    now: u64,
) -> Result<(), OperatorAdmissionError> {
    if evaluator.role() != LearningEvidenceRoleV1::Evaluator {
        return Err(OperatorAdmissionError::EvaluatorRole);
    }
    verify_signed_role_separation(generator, evaluator, now)?;
    if evaluator_id != &evaluator.principal().principal_id {
        return Err(OperatorAdmissionError::EvaluatorIdentity);
    }
    if evaluator_credential_digest != evaluator.principal().credential_chain_digest {
        return Err(OperatorAdmissionError::EvaluatorCredential);
    }
    // The signed payload is the structural receipt digest bytes. The learning
    // evidence verifier stores SHA-256(payload), so bind that exact payload here.
    let expected_payload_digest = Digest32::of_bytes(structural_receipt_digest.as_array());
    if evaluator.payload_digest() != expected_payload_digest {
        return Err(OperatorAdmissionError::EvidencePayload);
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OperatorAdmissionError {
    Closure(OperatorClosureError),
    Learned(LearnedOperatorError),
    WorldModel(WorldModelError),
    Dataset(DatasetReceiptError),
    Signed(SignedEvidenceError),
    DatasetBinding,
    EvidenceOutsideDataset,
    EvaluatorRole,
    EvaluatorIdentity,
    EvaluatorCredential,
    EvidencePayload,
}

impl fmt::Display for OperatorAdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OperatorAdmissionError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Closure(error) => Some(error),
            Self::Learned(error) => Some(error),
            Self::WorldModel(error) => Some(error),
            Self::Dataset(error) => Some(error),
            Self::Signed(error) => Some(error),
            Self::DatasetBinding
            | Self::EvidenceOutsideDataset
            | Self::EvaluatorRole
            | Self::EvaluatorIdentity
            | Self::EvaluatorCredential
            | Self::EvidencePayload => None,
        }
    }
}

impl From<OperatorClosureError> for OperatorAdmissionError {
    fn from(value: OperatorClosureError) -> Self {
        Self::Closure(value)
    }
}
impl From<LearnedOperatorError> for OperatorAdmissionError {
    fn from(value: LearnedOperatorError) -> Self {
        Self::Learned(value)
    }
}
impl From<WorldModelError> for OperatorAdmissionError {
    fn from(value: WorldModelError) -> Self {
        Self::WorldModel(value)
    }
}
impl From<DatasetReceiptError> for OperatorAdmissionError {
    fn from(value: DatasetReceiptError) -> Self {
        Self::Dataset(value)
    }
}
impl From<SignedEvidenceError> for OperatorAdmissionError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Signed(value)
    }
}

#[cfg(test)]
#[path = "admission_tests.rs"]
mod tests;

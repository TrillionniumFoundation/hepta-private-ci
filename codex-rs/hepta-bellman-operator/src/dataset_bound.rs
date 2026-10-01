//! Dataset admission at the authoritative ledger owner.
//!
//! V2 remains a structural compatibility API, not a production admission.
//! V3 borrows the actual `LedgerWriter`, authenticates its dataset freeze and
//! complete row commitment, and repeats admission immediately before fitting.
//! A verified input cannot be cloned, deserialized, or constructed from fields.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::DatasetReceiptError;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::dataset_freeze_signing_payload_v2;
#[cfg(any(test, feature = "qualification-unverified-input"))]
use codex_hepta_learning_ledger::verify_dataset_snapshot_receipt_v3;
use codex_hepta_learning_ledger::verify_signed_independent_roles_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[cfg(any(test, feature = "qualification-unverified-input"))]
use super::fit_tabular_operator_strict_v2;
#[cfg(any(test, feature = "qualification-unverified-input"))]
use super::fit_transition_model;
use crate::OperatorAdmissionStageV1;
use crate::StrictLearnedOperatorError;
#[cfg(any(test, feature = "qualification-unverified-input"))]
use crate::TabularOperatorArtifactV1;
use crate::TabularOperatorPlanV1;
#[cfg(any(test, feature = "qualification-unverified-input"))]
use crate::TabularWorldModelV1;
use crate::WorldModelError;
use crate::WorldModelSampleV1;

/// Signed materialization is bounded independently of the legacy fitter.
/// This is the same row bound as `LedgerWriter::read_dataset_records`.
pub const MAX_SIGNED_OPERATOR_ROWS: usize = 4096;

#[derive(Clone, Debug)]
#[cfg(any(test, feature = "qualification-unverified-input"))]
pub struct VerifiedTabularOperatorPlanV2 {
    plan: TabularOperatorPlanV1,
}

/// A single-use input tied to a root-authenticated, durable ledger owner.
/// Holding this borrow also prevents safe Rust callers from rotating that
/// owner's trust or appending a correction between admission and fitting.
///
/// ```compile_fail
/// use codex_hepta_bellman_operator::{fit_tabular_operator_verified_v3, TabularOperatorPlanV1};
/// fn bypass(plan: TabularOperatorPlanV1) {
///     let _ = fit_tabular_operator_verified_v3(plan, 50);
/// }
/// ```
pub struct VerifiedTabularOperatorPlanV3<'a> {
    plan: TabularOperatorPlanV1,
    admission: OwnerAdmission<'a>,
    verified_evidence: (VerifiedLearningEvidenceV1, VerifiedLearningEvidenceV1),
}

#[derive(Clone, Debug)]
#[cfg(any(test, feature = "qualification-unverified-input"))]
pub struct VerifiedWorldModelDatasetV2 {
    model_id: StableId,
    dataset_digest: Digest32,
    samples: Vec<WorldModelSampleV1>,
}

/// Single-use owner-bound world-model rows; there is no raw-row constructor.
pub struct VerifiedWorldModelDatasetV3<'a> {
    model_id: StableId,
    #[cfg_attr(
        not(feature = "qualification-unverified-input"),
        expect(
            dead_code,
            reason = "retains immutable authenticated rows for the compatibility fitter"
        )
    )]
    samples: Vec<WorldModelSampleV1>,
    admission: OwnerAdmission<'a>,
    verified_evidence: (VerifiedLearningEvidenceV1, VerifiedLearningEvidenceV1),
}

struct OwnerAdmission<'a> {
    owner: &'a LedgerWriter,
    receipt: DatasetSnapshotReceiptV3,
    freeze_evidence: SignedLearningEvidenceV1,
    row_evidence: SignedLearningEvidenceV1,
    admitted_at: u64,
}

impl fmt::Debug for VerifiedTabularOperatorPlanV3<'_> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("VerifiedTabularOperatorPlanV3")
            .field("artifact_id", &self.plan.artifact_id)
            .field("dataset_digest", &self.plan.dataset_digest)
            .finish_non_exhaustive()
    }
}

impl fmt::Debug for VerifiedWorldModelDatasetV3<'_> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("VerifiedWorldModelDatasetV3")
            .field("model_id", &self.model_id)
            .finish_non_exhaustive()
    }
}

#[cfg(any(test, feature = "qualification-unverified-input"))]
impl VerifiedTabularOperatorPlanV2 {
    #[cfg(feature = "qualification-unverified-input")]
    #[must_use]
    pub const fn admission_stage(&self) -> OperatorAdmissionStageV1 {
        OperatorAdmissionStageV1::StructurallyValidated
    }
}

impl<'a> VerifiedTabularOperatorPlanV3<'a> {
    pub(crate) fn into_verified_evidence(
        self,
    ) -> (
        &'a LedgerWriter,
        (VerifiedLearningEvidenceV1, VerifiedLearningEvidenceV1),
    ) {
        (self.admission.owner, self.verified_evidence)
    }
    #[must_use]
    pub const fn admission_stage(&self) -> OperatorAdmissionStageV1 {
        OperatorAdmissionStageV1::SourceAuthenticated
    }

    #[cfg(feature = "qualification-unverified-input")]
    #[must_use]
    pub fn ledger_head_digest(&self) -> Digest32 {
        self.admission.receipt.snapshot.ledger_head_digest
    }
    #[cfg(feature = "qualification-unverified-input")]
    #[must_use]
    pub fn trust_digest(&self) -> Digest32 {
        self.admission.owner.verifier().trust_digest()
    }
    #[cfg(feature = "qualification-unverified-input")]
    #[must_use]
    pub fn row_semantics_digest(&self) -> Digest32 {
        self.admission.row_evidence.payload_digest
    }
}

#[cfg(any(test, feature = "qualification-unverified-input"))]
impl VerifiedWorldModelDatasetV2 {
    #[cfg(feature = "qualification-unverified-input")]
    #[must_use]
    pub const fn admission_stage(&self) -> OperatorAdmissionStageV1 {
        OperatorAdmissionStageV1::StructurallyValidated
    }
}

impl<'a> VerifiedWorldModelDatasetV3<'a> {
    pub(crate) fn into_verified_evidence(
        self,
    ) -> (
        &'a LedgerWriter,
        (VerifiedLearningEvidenceV1, VerifiedLearningEvidenceV1),
    ) {
        (self.admission.owner, self.verified_evidence)
    }
    #[must_use]
    pub const fn admission_stage(&self) -> OperatorAdmissionStageV1 {
        OperatorAdmissionStageV1::SourceAuthenticated
    }

    #[cfg(feature = "qualification-unverified-input")]
    #[must_use]
    pub fn ledger_head_digest(&self) -> Digest32 {
        self.admission.receipt.snapshot.ledger_head_digest
    }
    #[cfg(feature = "qualification-unverified-input")]
    #[must_use]
    pub fn trust_digest(&self) -> Digest32 {
        self.admission.owner.verifier().trust_digest()
    }
    #[cfg(feature = "qualification-unverified-input")]
    #[must_use]
    pub fn row_semantics_digest(&self) -> Digest32 {
        self.admission.row_evidence.payload_digest
    }
}

#[cfg(any(test, feature = "qualification-unverified-input"))]
pub fn verify_tabular_operator_plan_v2(
    plan: TabularOperatorPlanV1,
    receipt: &DatasetSnapshotReceiptV3,
    now: u64,
) -> Result<VerifiedTabularOperatorPlanV2, OperatorDatasetBindingError> {
    if plan.samples.is_empty() || plan.samples.len() > super::learned::MAX_SAMPLES {
        return Err(OperatorDatasetBindingError::Learned(
            crate::LearnedOperatorError::SampleLimit.into(),
        ));
    }
    verify_dataset_snapshot_receipt_v3(receipt, now)?;
    verify_tabular_plan_binding(&plan, receipt)?;
    Ok(VerifiedTabularOperatorPlanV2 { plan })
}

#[cfg(any(test, feature = "qualification-unverified-input"))]
pub fn fit_tabular_operator_verified_v2(
    verified: VerifiedTabularOperatorPlanV2,
) -> Result<TabularOperatorArtifactV1, OperatorDatasetBindingError> {
    fit_tabular_operator_strict_v2(verified.plan).map_err(OperatorDatasetBindingError::Learned)
}

/// Both attestations use the owner's currently activated signer registry.
/// `freeze_evidence` must be the evaluator signature used by `freeze_dataset`;
/// the independently controlled observer signs `tabular_training_signing_payload_v2`.
pub fn verify_tabular_operator_plan_v3<'a>(
    plan: TabularOperatorPlanV1,
    receipt: &DatasetSnapshotReceiptV3,
    owner: &'a LedgerWriter,
    freeze_evidence: &SignedLearningEvidenceV1,
    row_evidence: &SignedLearningEvidenceV1,
    now: u64,
) -> Result<VerifiedTabularOperatorPlanV3<'a>, OperatorDatasetBindingError> {
    let payload = tabular_training_signing_payload_v2(&plan, receipt, owner)?;
    let admission = OwnerAdmission {
        owner,
        receipt: receipt.clone(),
        freeze_evidence: freeze_evidence.clone(),
        row_evidence: row_evidence.clone(),
        admitted_at: now,
    };
    let verified_evidence = admission.revalidate(&payload, now)?;
    Ok(VerifiedTabularOperatorPlanV3 {
        plan,
        admission,
        verified_evidence,
    })
}

/// Revalidate expiry, current ledger membership and signer epoch at use, not
/// only when the opaque input was first issued. `now` comes from the host clock.
#[cfg(any(test, feature = "qualification-unverified-input"))]
pub fn fit_tabular_operator_verified_v3(
    verified: VerifiedTabularOperatorPlanV3<'_>,
    now: u64,
) -> Result<TabularOperatorArtifactV1, OperatorDatasetBindingError> {
    let payload = tabular_training_signing_payload_v2(
        &verified.plan,
        &verified.admission.receipt,
        verified.admission.owner,
    )?;
    verified.admission.revalidate(&payload, now)?;
    fit_tabular_operator_strict_v2(verified.plan).map_err(OperatorDatasetBindingError::Learned)
}

#[cfg(any(test, feature = "qualification-unverified-input"))]
pub fn verify_world_model_dataset_v2(
    model_id: StableId,
    samples: Vec<WorldModelSampleV1>,
    receipt: &DatasetSnapshotReceiptV3,
    now: u64,
) -> Result<VerifiedWorldModelDatasetV2, OperatorDatasetBindingError> {
    if samples.is_empty() {
        return Err(OperatorDatasetBindingError::WorldModel(
            WorldModelError::EmptyDataset,
        ));
    }
    if samples.len() > super::world_model::MAX_SAMPLES {
        return Err(OperatorDatasetBindingError::WorldModel(
            WorldModelError::SampleLimit,
        ));
    }
    verify_dataset_snapshot_receipt_v3(receipt, now)?;
    verify_evidence_membership(
        &receipt.snapshot.source_record_digests,
        samples.iter().map(|sample| sample.evidence_digest),
    )?;
    Ok(VerifiedWorldModelDatasetV2 {
        model_id,
        dataset_digest: receipt.snapshot.dataset_digest,
        samples,
    })
}

#[allow(clippy::too_many_arguments)]
pub fn verify_world_model_dataset_v3<'a>(
    model_id: StableId,
    samples: Vec<WorldModelSampleV1>,
    receipt: &DatasetSnapshotReceiptV3,
    owner: &'a LedgerWriter,
    freeze_evidence: &SignedLearningEvidenceV1,
    row_evidence: &SignedLearningEvidenceV1,
    now: u64,
) -> Result<VerifiedWorldModelDatasetV3<'a>, OperatorDatasetBindingError> {
    let payload = world_model_training_signing_payload_v2(&model_id, &samples, receipt, owner)?;
    let admission = OwnerAdmission {
        owner,
        receipt: receipt.clone(),
        freeze_evidence: freeze_evidence.clone(),
        row_evidence: row_evidence.clone(),
        admitted_at: now,
    };
    let verified_evidence = admission.revalidate(&payload, now)?;
    Ok(VerifiedWorldModelDatasetV3 {
        model_id,
        samples,
        admission,
        verified_evidence,
    })
}

#[cfg(any(test, feature = "qualification-unverified-input"))]
pub fn fit_transition_model_verified_v2(
    verified: VerifiedWorldModelDatasetV2,
) -> Result<TabularWorldModelV1, OperatorDatasetBindingError> {
    fit_transition_model(verified.model_id, verified.dataset_digest, verified.samples)
        .map_err(OperatorDatasetBindingError::WorldModel)
}

#[cfg(feature = "qualification-unverified-input")]
pub fn fit_transition_model_verified_v3(
    verified: VerifiedWorldModelDatasetV3<'_>,
    now: u64,
) -> Result<TabularWorldModelV1, OperatorDatasetBindingError> {
    let payload = world_model_training_signing_payload_v2(
        &verified.model_id,
        &verified.samples,
        &verified.admission.receipt,
        verified.admission.owner,
    )?;
    verified.admission.revalidate(&payload, now)?;
    fit_transition_model(
        verified.model_id,
        verified.admission.receipt.snapshot.dataset_digest,
        verified.samples,
    )
    .map_err(OperatorDatasetBindingError::WorldModel)
}

impl OwnerAdmission<'_> {
    fn revalidate(
        &self,
        payload: &[u8],
        now: u64,
    ) -> Result<(VerifiedLearningEvidenceV1, VerifiedLearningEvidenceV1), OperatorDatasetBindingError>
    {
        if now < self.admitted_at {
            return Err(OperatorDatasetBindingError::ClockRegression);
        }
        self.owner
            .revalidate_trust_at(now)
            .map_err(|error| owner_failure(OwnerDatasetOperationV1::RevalidateTrust, error))?;
        let plan = DatasetFreezePlanV2 {
            snapshot_id: self.receipt.snapshot.snapshot_id.clone(),
            objective_digest: self.receipt.snapshot.objective_digest,
            inclusion_policy_digest: self.receipt.inclusion_policy_digest,
        };
        // Re-derive every field (including cuts/frontiers/producer) from the
        // current durable owner, rather than accepting a rehashed public struct.
        let expected = self
            .owner
            .freeze_dataset(plan.clone(), &self.freeze_evidence, now)
            .map_err(|error| owner_failure(OwnerDatasetOperationV1::FreezeDataset, error))?;
        if expected != self.receipt {
            return Err(OperatorDatasetBindingError::TrustContextMismatch);
        }
        self.owner
            .read_dataset_records(&self.receipt, now)
            .map_err(|error| owner_failure(OwnerDatasetOperationV1::ReadDatasetRecords, error))?;
        let snapshot = self
            .owner
            .snapshot()
            .map_err(|error| owner_failure(OwnerDatasetOperationV1::Snapshot, error))?;
        let freeze_payload = dataset_freeze_signing_payload_v2(&snapshot, &plan)
            .map_err(|error| owner_failure(OwnerDatasetOperationV1::EncodeFreezePayload, error))?;
        let verifier = self.owner.verifier();
        let evaluator = verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &self.freeze_evidence,
            &freeze_payload,
            now,
        )?;
        let observer = verifier.verify(
            LearningEvidenceRoleV1::Observer,
            &self.row_evidence,
            payload,
            now,
        )?;
        verify_signed_independent_roles_v1(&evaluator, &observer, now)?;
        Ok((evaluator, observer))
    }
}

fn verify_tabular_plan_binding(
    plan: &TabularOperatorPlanV1,
    receipt: &DatasetSnapshotReceiptV3,
) -> Result<(), OperatorDatasetBindingError> {
    if plan.dataset_digest != receipt.snapshot.dataset_digest {
        return Err(OperatorDatasetBindingError::DatasetDigestMismatch);
    }
    if plan.objective_digest != receipt.snapshot.objective_digest {
        return Err(OperatorDatasetBindingError::ObjectiveDigestMismatch);
    }
    verify_evidence_membership(
        &receipt.snapshot.source_record_digests,
        plan.samples.iter().map(|sample| sample.evidence_digest),
    )
}

fn verify_evidence_membership(
    frozen_records: &[Digest32],
    actual: impl ExactSizeIterator<Item = Digest32>,
) -> Result<(), OperatorDatasetBindingError> {
    if actual.len() != frozen_records.len() {
        return Err(OperatorDatasetBindingError::EvidenceSetMismatch);
    }
    let mut seen = std::collections::BTreeSet::new();
    for digest in actual {
        if frozen_records.binary_search(&digest).is_err() {
            return Err(OperatorDatasetBindingError::EvidenceSetMismatch);
        }
        if !seen.insert(digest) {
            return Err(OperatorDatasetBindingError::DuplicateEvidence);
        }
    }
    Ok(())
}

#[path = "row_commitment.rs"]
mod row_commitment;
#[cfg(test)]
use row_commitment::canonical_tabular_row_semantics_v1;
#[cfg(test)]
use row_commitment::canonical_world_model_row_semantics_v1;
pub use row_commitment::tabular_training_signing_payload_v2;
pub use row_commitment::world_model_training_signing_payload_v2;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OwnerDatasetOperationV1 {
    RevalidateTrust,
    FreezeDataset,
    ReadDatasetRecords,
    Snapshot,
    EncodeFreezePayload,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OwnerDatasetFailureV1 {
    pub operation: OwnerDatasetOperationV1,
    pub message: String,
}

impl fmt::Display for OwnerDatasetFailureV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{:?}: {}", self.operation, self.message)
    }
}
impl StdError for OwnerDatasetFailureV1 {}

fn owner_failure(
    operation: OwnerDatasetOperationV1,
    error: impl fmt::Display,
) -> OperatorDatasetBindingError {
    OperatorDatasetBindingError::Owner(OwnerDatasetFailureV1 {
        operation,
        message: error.to_string(),
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OperatorDatasetBindingError {
    DatasetReceipt(DatasetReceiptError),
    SignedEvidence(SignedEvidenceError),
    DatasetDigestMismatch,
    ObjectiveDigestMismatch,
    EvidenceSetMismatch,
    TrustContextMismatch,
    DuplicateEvidence,
    DuplicateIdentity,
    Bounds,
    ClockRegression,
    Arithmetic,
    Owner(OwnerDatasetFailureV1),
    Learned(StrictLearnedOperatorError),
    WorldModel(WorldModelError),
}

impl fmt::Display for OperatorDatasetBindingError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for OperatorDatasetBindingError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::DatasetReceipt(error) => Some(error),
            Self::SignedEvidence(error) => Some(error),
            Self::Owner(error) => Some(error),
            Self::Learned(error) => Some(error),
            Self::WorldModel(error) => Some(error),
            Self::DatasetDigestMismatch
            | Self::ObjectiveDigestMismatch
            | Self::EvidenceSetMismatch
            | Self::TrustContextMismatch
            | Self::DuplicateEvidence
            | Self::DuplicateIdentity
            | Self::Bounds
            | Self::ClockRegression
            | Self::Arithmetic => None,
        }
    }
}
impl From<DatasetReceiptError> for OperatorDatasetBindingError {
    fn from(value: DatasetReceiptError) -> Self {
        Self::DatasetReceipt(value)
    }
}
impl From<SignedEvidenceError> for OperatorDatasetBindingError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::SignedEvidence(value)
    }
}

#[cfg(test)]
#[path = "owner_dataset_tests.rs"]
mod owner_tests;
#[cfg(test)]
#[path = "dataset_bound_tests.rs"]
mod tests;

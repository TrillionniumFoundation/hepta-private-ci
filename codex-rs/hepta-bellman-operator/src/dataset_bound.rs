//! Qualification-fixture receipt/evidence membership checks.
//!
//! Available only in tests or with `unchecked-qualification-inputs`. These
//! checks bind receipt identities and the named evidence set, NOT the semantic
//! derivation of caller-supplied targets, actions, states or outcomes. They are
//! not an authenticated production training ingress. Default product consumers
//! use owner_terminal materialization of actual current LedgerWriter records.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::DatasetReceiptError;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::verify_dataset_snapshot_receipt_v3;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::StrictLearnedOperatorError;
use crate::TabularOperatorArtifactV1;
use crate::TabularOperatorPlanV1;
use crate::TabularWorldModelV1;
use crate::WorldModelError;
use crate::WorldModelSampleV1;
use crate::fit_tabular_operator_strict_v2;
use crate::fit_transition_model;

/// Receipt identities and source-record membership checked for a qualification
/// fixture. Numerical targets and feature/action labels are not source-attested.
#[derive(Clone, Debug)]
pub struct VerifiedTabularOperatorPlanV2 {
    plan: TabularOperatorPlanV1,
}

/// Fixture evidence membership only; transition labels/outcomes remain
/// caller-supplied and must never be promoted to owner-backed production facts.
#[derive(Clone, Debug)]
pub struct VerifiedWorldModelDatasetV2 {
    model_id: StableId,
    dataset_digest: Digest32,
    samples: Vec<WorldModelSampleV1>,
}

pub fn verify_tabular_operator_plan_v2(
    plan: TabularOperatorPlanV1,
    receipt: &DatasetSnapshotReceiptV3,
    now: u64,
) -> Result<VerifiedTabularOperatorPlanV2, OperatorDatasetBindingError> {
    verify_dataset_snapshot_receipt_v3(receipt, now)?;
    if plan.dataset_digest != receipt.snapshot.dataset_digest {
        return Err(OperatorDatasetBindingError::DatasetDigestMismatch);
    }
    if plan.objective_digest != receipt.snapshot.objective_digest {
        return Err(OperatorDatasetBindingError::ObjectiveDigestMismatch);
    }
    verify_evidence_membership(
        &receipt.snapshot.source_record_digests,
        plan.samples.iter().map(|sample| sample.evidence_digest),
    )?;
    Ok(VerifiedTabularOperatorPlanV2 { plan })
}

pub fn fit_tabular_operator_verified_v2(
    verified: VerifiedTabularOperatorPlanV2,
) -> Result<TabularOperatorArtifactV1, OperatorDatasetBindingError> {
    fit_tabular_operator_strict_v2(verified.plan).map_err(OperatorDatasetBindingError::Learned)
}

pub fn verify_world_model_dataset_v2(
    model_id: StableId,
    samples: Vec<WorldModelSampleV1>,
    receipt: &DatasetSnapshotReceiptV3,
    now: u64,
) -> Result<VerifiedWorldModelDatasetV2, OperatorDatasetBindingError> {
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

pub fn fit_transition_model_verified_v2(
    verified: VerifiedWorldModelDatasetV2,
) -> Result<TabularWorldModelV1, OperatorDatasetBindingError> {
    fit_transition_model(verified.model_id, verified.dataset_digest, verified.samples)
        .map_err(OperatorDatasetBindingError::WorldModel)
}

fn verify_evidence_membership(
    frozen_records: &[Digest32],
    actual: impl Iterator<Item = Digest32>,
) -> Result<(), OperatorDatasetBindingError> {
    let frozen = frozen_records
        .iter()
        .copied()
        .collect::<std::collections::BTreeSet<_>>();
    let actual = actual.collect::<std::collections::BTreeSet<_>>();
    if actual != frozen {
        return Err(OperatorDatasetBindingError::EvidenceSetMismatch);
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OperatorDatasetBindingError {
    DatasetReceipt(DatasetReceiptError),
    DatasetDigestMismatch,
    ObjectiveDigestMismatch,
    EvidenceSetMismatch,
    Learned(StrictLearnedOperatorError),
    WorldModel(WorldModelError),
}

impl fmt::Display for OperatorDatasetBindingError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OperatorDatasetBindingError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::DatasetReceipt(error) => Some(error),
            Self::Learned(error) => Some(error),
            Self::WorldModel(error) => Some(error),
            Self::DatasetDigestMismatch
            | Self::ObjectiveDigestMismatch
            | Self::EvidenceSetMismatch => None,
        }
    }
}

impl From<DatasetReceiptError> for OperatorDatasetBindingError {
    fn from(value: DatasetReceiptError) -> Self {
        Self::DatasetReceipt(value)
    }
}

#[cfg(test)]
#[path = "dataset_bound_tests.rs"]
mod tests;

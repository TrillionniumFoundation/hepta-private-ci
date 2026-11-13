//! Prepare real Dataset material before freezing the original Root row rule.
//! Evaluator freeze authorization and later Observer stage receipts are separate.
//! This capability opens no file, signs nothing and grants no Root authority.

use std::io;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationOwnersV1;
use codex_hepta_learning_artifacts::LearningIterationRequestV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LedgerSnapshot;
use codex_hepta_learning_ledger::LedgerWitnessFrontier;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::dataset_freeze_signing_payload_v2;
use codex_hepta_learning_ledger::freeze_dataset_from_ledger;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::CellQ24DatasetErrorV1;
use super::CellQ24DatasetProjectionV1;
use super::CellQ24DatasetTaskV1;
use super::CellQ24PrivateHeadV1;
use super::CellQ24SgdRuleV1;
use super::CellQ24SingleHeadTrainingPlanV1;
use super::CellQ24TrainingBatchV1;
use super::CellQ24TrainingErrorV1;
use super::CellQ24TrainingPlanErrorV1;
use super::LoadedCellQ24ModelV1;
use super::cell_q24_dataset_run_snapshot_digest_v1;
use super::cell_q24_single_head_update_rule_v1;
use super::dataset::HistoricalDatasetLedgerV1;
use super::dataset::OriginalDatasetLedgerV1;
use super::dataset::OriginalDatasetOperationV1;
use crate::AgentdIdentity;
use crate::CircuitTaskSourcePublicationV1;
use crate::HostAuthorityLearningProfileV1;

#[path = "cell_q24_dataset_preparation.rs"]
mod capture;
#[path = "cell_q24_freeze_operation.rs"]
mod freeze_operation;
#[path = "cell_q24_dataset_freeze_owner.rs"]
mod freeze_owner;
#[path = "cell_q24_dataset_historical_freezer.rs"]
mod historical_freezer;
#[path = "cell_q24_dataset_historical_preparation.rs"]
mod historical_preparation;
#[path = "cell_q24_prepared_operation.rs"]
mod operation;
#[path = "cell_q24_prepared_learning.rs"]
mod prepared;
#[path = "cell_q24_prepared_training_material.rs"]
mod training_material;
use freeze_operation::OriginalFreezePreparationReadV1;
pub use freeze_owner::OriginalCellQ24DatasetFreezeErrorV1;
pub use freeze_owner::OriginalCellQ24DatasetFreezeOwnerV1;
pub use freeze_owner::OriginalCellQ24DatasetFreezeSigningConfigV1;
pub(crate) use operation::OriginalPreparedReadV1;

#[derive(Debug, thiserror::Error)]
pub enum CellQ24LearningPreparationErrorV1 {
    #[error("original Q24 preparation binding: {0}")]
    Binding(&'static str),
    #[error("original Dataset: {0}")]
    Dataset(#[from] CellQ24DatasetErrorV1),
    #[error("original ledger: {0}")]
    Ledger(#[from] ProductionLedgerError),
    #[error("original Evaluator authorization: {0}")]
    Authentication(#[from] SignedEvidenceError),
    #[error("original training material: {0}")]
    Training(#[from] CellQ24TrainingErrorV1),
    #[error("original row plan: {0}")]
    Plan(#[from] CellQ24TrainingPlanErrorV1),
    #[error("original iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original Root profile: {0}")]
    Root(#[from] io::Error),
}
type Error = CellQ24LearningPreparationErrorV1;

/// Host-frozen configuration. Source bytes and targets are never accepted here.
#[derive(Clone)]
pub struct CellQ24LearningPreparationConfigV1 {
    pub request: LearningIterationRequestV1,
    pub owners: LearningIterationOwnersV1,
    pub baseline: Arc<LoadedCellQ24ModelV1>,
    pub head: CellQ24PrivateHeadV1,
    pub rule: CellQ24SgdRuleV1,
    pub projection: CellQ24DatasetProjectionV1,
    pub snapshot_id: StableId,
}

/// Retain these original bytes for recovery. They are not source capabilities;
/// recovery also requires the same live ledger and captured task owners.
#[derive(Clone)]
pub struct CellQ24FrozenDatasetV1 {
    pub snapshot: LedgerSnapshot,
    pub receipt: DatasetSnapshotReceiptV3,
    pub authorization: SignedLearningEvidenceV1,
}

pub struct CellQ24DatasetFreezePreparationV1 {
    config: CellQ24LearningPreparationConfigV1,
    ledger: OriginalDatasetLedgerV1,
    tasks: Vec<CellQ24DatasetTaskV1>,
    snapshot: LedgerSnapshot,
    frontier: LedgerWitnessFrontier,
}

/// Values read from original owners, not caller-authored stage observations.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellQ24PreparedLearningFactsV1 {
    experience: LearningIterationObservationV1,
    dataset: LearningIterationObservationV1,
    experience_evidence: Digest32,
    dataset_evidence: Digest32,
}
impl CellQ24PreparedLearningFactsV1 {
    pub fn experience(&self) -> &LearningIterationObservationV1 {
        &self.experience
    }
    pub fn dataset(&self) -> &LearningIterationObservationV1 {
        &self.dataset
    }
    pub fn experience_evidence_digest(&self) -> Digest32 {
        self.experience_evidence
    }
    pub fn dataset_evidence_digest(&self) -> Digest32 {
        self.dataset_evidence
    }
}

pub struct CellQ24PreparedTrainingMaterialV1 {
    pub plan: CellQ24SingleHeadTrainingPlanV1,
    pub batch: CellQ24TrainingBatchV1,
    pub rule: CellQ24SgdRuleV1,
}

/// Holds the real HQ24T002 source capability and one immutable derived scope.
/// Root still registers an empty initial checkpoint through its original lane.
pub struct CellQ24PreparedLearningV1 {
    config: CellQ24LearningPreparationConfigV1,
    batch: CellQ24TrainingBatchV1,
    frozen: CellQ24FrozenDatasetV1,
    initial: LearningIterationSnapshotV1,
    scope: FrozenLearningScopeV2,
    facts: CellQ24PreparedLearningFactsV1,
}

fn require_configuration(
    config: &CellQ24LearningPreparationConfigV1,
    tasks: &[CellQ24DatasetTaskV1],
) -> Result<CircuitTaskSourcePublicationV1, Error> {
    require_configuration_profile(config, tasks.len())?;
    let publications = tasks
        .iter()
        .map(|task| task.read_current().cloned())
        .collect::<Result<Vec<_>, _>>()?;
    require_configuration_data(config, &publications)
}

fn require_configuration_profile(
    config: &CellQ24LearningPreparationConfigV1,
    count: usize,
) -> Result<Digest32, Error> {
    LearningIterationCoordinatorV1::new(config.request.clone(), config.owners.clone())?;
    let bundle = config
        .request
        .selected_bundle
        .digest()
        .map_err(LearningIterationError::from)?;
    let index = match config.head {
        CellQ24PrivateHeadV1::Drive { index } | CellQ24PrivateHeadV1::Prediction { index } => index,
    };
    if !(1..=256).contains(&count)
        || config.baseline.components() != &config.request.selected_bundle.components
        || config.projection.baseline_bundle != bundle
        || usize::from(config.projection.input_width) != config.baseline.input_width()
        || usize::from(index) >= config.baseline.output_width()
    {
        return Err(Error::Binding("original baseline, projection and head"));
    }
    Ok(bundle)
}

fn require_configuration_data(
    config: &CellQ24LearningPreparationConfigV1,
    publications: &[CircuitTaskSourcePublicationV1],
) -> Result<CircuitTaskSourcePublicationV1, Error> {
    let bundle = require_configuration_profile(config, publications.len())?;
    let mut source = None;
    for publication in publications {
        let input = publication.input();
        if input.scope.agent_id != config.request.agent_id
            || input.scope.cell_id != config.request.cell_id
            || input.scope.principal_digest.to_string() != config.request.principal_id.as_str()
            || input.objective_digest != config.request.envelope.objective_digest
            || publication.original_record().snapshot.run_id != input.scope.run_id
            || publication.original_record().snapshot.objective_digest != input.objective_digest
            || publication.bundle_digest() != bundle
        {
            return Err(Error::Binding("original task scope and baseline"));
        }
        if input.scope.run_id == config.request.source_run_id {
            if source.is_some()
                || publication.history_digest().as_str()
                    != config.request.completed_task_receipt.to_string()
            {
                return Err(Error::Binding("original completed task receipt"));
            }
            source = Some(publication.clone());
        }
    }
    source.ok_or(Error::Binding("original completed task absent"))
}

fn now() -> Result<u64, Error> {
    Ok(SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| Error::Binding("system clock"))?
        .as_secs())
}

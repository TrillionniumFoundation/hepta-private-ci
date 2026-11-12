//! Host-frozen preparation data for the actual fresh A source.
//! The completed-task pin is external observation data checked by the actual
//! Producer against its live source. It is never taken from a Control ACK.

use std::sync::Arc;
use codex_hepta_learning_artifacts::{CellCompatibilityBundleV1, IterationEnvelopeV1,
    LearningIterationBudgetV1, LearningIterationOwnersV1, LearningIterationRequestV1};
use codex_hepta_types::{Digest32, StableId};
use serde::{Deserialize, Serialize};
use crate::{AgentdError, CellQ24DatasetProjectionV1, CellQ24LearningPreparationConfigV1,
    CellQ24PrivateHeadV1, CellQ24SgdRuleV1, LoadedCellQ24ModelV1};
use super::{deployment_error, deployment_refused};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalEnvelopeData {
    pub envelope_id: String,
    pub base_commit: [u8; 32],
    pub base_tree: [u8; 32],
    pub objective_digest: [u8; 32],
    pub grammar_digest: [u8; 32],
    pub maximum_files: u16,
    pub maximum_diff_bytes: u64,
    pub maximum_candidates: u16,
    pub maximum_parallel_sandboxes: u8,
    pub expiry_unix_seconds: u64,
}
impl OriginalEnvelopeData {
    fn original(&self) -> Result<IterationEnvelopeV1, AgentdError> {
        Ok(IterationEnvelopeV1 {
            envelope_id: StableId::new(&self.envelope_id).map_err(deployment_error)?,
            base_commit: Digest32::from_array(self.base_commit),
            base_tree: Digest32::from_array(self.base_tree),
            objective_digest: Digest32::from_array(self.objective_digest),
            grammar_digest: Digest32::from_array(self.grammar_digest),
            maximum_files: self.maximum_files, maximum_diff_bytes: self.maximum_diff_bytes,
            maximum_candidates: self.maximum_candidates,
            maximum_parallel_sandboxes: self.maximum_parallel_sandboxes,
            expiry_unix_seconds: self.expiry_unix_seconds,
        })
    }
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalLearningBudgetData {
    pub maximum_dataset_rows: u32,
    pub maximum_dataset_bytes: u64,
    pub maximum_training_steps: u64,
    pub maximum_training_milliseconds: u64,
    pub maximum_artifact_bytes: u64,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalLearningRequestData {
    pub operation_id: String,
    pub principal_id: String,
    pub agent_id: String,
    pub cell_id: String,
    pub source_run_id: String,
    pub completed_task_receipt: [u8; 32],
    pub selected_artifact_digest: [u8; 32],
    pub evaluation_profile: [u8; 32],
    pub selected_bundle_digest: [u8; 32],
    pub envelope: OriginalEnvelopeData,
    pub budget: OriginalLearningBudgetData,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalIterationOwnersData {
    pub evidence_trust_digest: [u8; 32],
    pub experience: String,
    pub dataset: String,
    pub trainer: String,
    pub evaluator: String,
    pub proposal: String,
    pub selector: String,
    pub next_use_observer: String,
}
#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum OriginalPrivateHeadData {
    Drive { index: u16 },
    Prediction { index: u16 },
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalPreparationData {
    pub request: OriginalLearningRequestData,
    pub owners: OriginalIterationOwnersData,
    pub head: OriginalPrivateHeadData,
    pub epochs: u16,
    pub learning_rate_q24: i64,
    pub inherited_inclusion_policy: [u8; 32],
    pub unit_profile_digest: [u8; 32],
    pub input_width: u16,
    pub snapshot_id: String,
}
impl OriginalPreparationData {
    pub(super) fn original(
        &self, baseline: Arc<LoadedCellQ24ModelV1>, bundle: &CellCompatibilityBundleV1,
    ) -> Result<CellQ24LearningPreparationConfigV1, AgentdError> {
        let expected = Digest32::from_array(self.request.selected_bundle_digest);
        if bundle.digest().map_err(deployment_error)? != expected
            || baseline.components() != &bundle.components
        {
            return Err(deployment_refused("preparation differs from the actual Initial baseline"));
        }
        let data = &self.request;
        let budget = &data.budget;
        let request = LearningIterationRequestV1 {
            operation_id: StableId::new(&data.operation_id).map_err(deployment_error)?,
            principal_id: StableId::new(&data.principal_id).map_err(deployment_error)?,
            agent_id: StableId::new(&data.agent_id).map_err(deployment_error)?,
            cell_id: StableId::new(&data.cell_id).map_err(deployment_error)?,
            source_run_id: StableId::new(&data.source_run_id).map_err(deployment_error)?,
            completed_task_receipt: Digest32::from_array(data.completed_task_receipt),
            selected_artifact_digest: Digest32::from_array(data.selected_artifact_digest),
            evaluation_profile: Digest32::from_array(data.evaluation_profile),
            selected_bundle: bundle.clone(), envelope: data.envelope.original()?,
            budget: LearningIterationBudgetV1 {
                maximum_dataset_rows: budget.maximum_dataset_rows,
                maximum_dataset_bytes: budget.maximum_dataset_bytes,
                maximum_training_steps: budget.maximum_training_steps,
                maximum_training_milliseconds: budget.maximum_training_milliseconds,
                maximum_artifact_bytes: budget.maximum_artifact_bytes,
            },
        };
        let owner = &self.owners;
        Ok(CellQ24LearningPreparationConfigV1 {
            request,
            owners: LearningIterationOwnersV1 {
                evidence_trust_digest: Digest32::from_array(owner.evidence_trust_digest),
                experience: StableId::new(&owner.experience).map_err(deployment_error)?,
                dataset: StableId::new(&owner.dataset).map_err(deployment_error)?,
                trainer: StableId::new(&owner.trainer).map_err(deployment_error)?,
                evaluator: StableId::new(&owner.evaluator).map_err(deployment_error)?,
                proposal: StableId::new(&owner.proposal).map_err(deployment_error)?,
                selector: StableId::new(&owner.selector).map_err(deployment_error)?,
                next_use_observer: StableId::new(&owner.next_use_observer).map_err(deployment_error)?,
            },
            baseline,
            head: match self.head {
                OriginalPrivateHeadData::Drive { index } => CellQ24PrivateHeadV1::Drive { index },
                OriginalPrivateHeadData::Prediction { index } => CellQ24PrivateHeadV1::Prediction { index },
            },
            rule: CellQ24SgdRuleV1 { epochs: self.epochs, learning_rate_q24: self.learning_rate_q24 },
            projection: CellQ24DatasetProjectionV1 {
                inherited_inclusion_policy: Digest32::from_array(self.inherited_inclusion_policy),
                unit_profile_digest: Digest32::from_array(self.unit_profile_digest),
                baseline_bundle: expected, input_width: self.input_width,
            },
            snapshot_id: StableId::new(&self.snapshot_id).map_err(deployment_error)?,
        })
    }
}

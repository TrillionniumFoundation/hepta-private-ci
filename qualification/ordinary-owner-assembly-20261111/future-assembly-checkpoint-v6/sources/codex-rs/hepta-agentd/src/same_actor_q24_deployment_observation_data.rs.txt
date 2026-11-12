//! Exact data exported from the actual Training/decision observations.
//! These descriptions carry no receipt constructor, task admission or Root
//! authority. Independent actors must reconcile them with their real sources.

use std::sync::Arc;
use codex_hepta_learning_artifacts::{
    LearningIterationSnapshotV1, learning_iteration_receipt_signing_bytes_v1,
};
use serde::Serialize;
use crate::{AgentdError, CellQ24TrainingOutcomeV1, LoadedCellQ24ModelV1,
    OriginalCellQ24TrainingMaterialV1};
use super::bundle_data::OriginalBundleData;
use super::learning_data::SignedEvidenceData;
use super::{deployment_error, deployment_refused};

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalTrainingNotice {
    pub schema_version: u32,
    pub purpose: &'static str,
    pub phase: String,
    pub learning_operation: String,
    pub dataset_head: [u8; 32],
    pub training_head: [u8; 32],
    pub receipt_signing_bytes: Vec<u8>,
    pub attestation: SignedEvidenceData,
    pub candidate_bundle: OriginalBundleData,
    pub heads: Vec<u8>,
    pub batch_digest: [u8; 32],
    pub optimizer_rule: [u8; 32],
    pub update_rule: [u8; 32],
    pub optimizer_steps: u64,
    pub squared_error_before_q48: String,
    pub squared_error_after_q48: String,
    pub elapsed_microseconds: u64,
}
impl OriginalTrainingNotice {
    pub(super) fn from_original(
        phase: &str,
        snapshot: &LearningIterationSnapshotV1,
        material: OriginalCellQ24TrainingMaterialV1,
    ) -> Result<(Self, Arc<LoadedCellQ24ModelV1>), AgentdError> {
        if material.training() != snapshot {
            return Err(deployment_refused("Training notice differs from its actual readback"));
        }
        let dataset_head = material.dataset().head_digest.into_array();
        let completion = material.into_completion();
        let CellQ24TrainingOutcomeV1::Candidate(candidate) = completion.outcome else {
            // An authenticated NoUpdate follows the existing Decision branch;
            // it is not reclassified as a candidate for an independent B run.
            return Err(deployment_refused("actual NoUpdate has no independent-B candidate"));
        };
        let candidate = *candidate;
        let notice = Self {
            schema_version: 1,
            purpose: "hepta.same-actor-q24-deployment.original-training.v1",
            phase: phase.to_owned(),
            learning_operation: snapshot.request.operation_id.as_str().to_owned(),
            dataset_head, training_head: snapshot.head_digest.into_array(),
            receipt_signing_bytes: learning_iteration_receipt_signing_bytes_v1(
                &completion.receipt,
            ).map_err(deployment_error)?,
            attestation: SignedEvidenceData::from_original(&completion.attestation),
            candidate_bundle: OriginalBundleData::from_original(&candidate.bundle),
            heads: candidate.heads,
            batch_digest: candidate.metrics.batch_digest.into_array(),
            optimizer_rule: candidate.metrics.optimizer_rule.into_array(),
            update_rule: candidate.metrics.update_rule.into_array(),
            optimizer_steps: candidate.metrics.optimizer_steps,
            squared_error_before_q48: candidate.metrics.squared_error_before_q48.to_string(),
            squared_error_after_q48: candidate.metrics.squared_error_after_q48.to_string(),
            elapsed_microseconds: candidate.metrics.elapsed_microseconds,
        };
        Ok((notice, Arc::new(candidate.model)))
    }
}

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalDecisionNotice {
    pub schema_version: u32,
    pub purpose: &'static str,
    pub phase: String,
    pub learning_operation: String,
    pub actual_head: [u8; 32],
    pub original_receipt_signing_bytes: Vec<Vec<u8>>,
}
impl OriginalDecisionNotice {
    pub(super) fn from_original(
        phase: &str, snapshot: &LearningIterationSnapshotV1,
    ) -> Result<Self, AgentdError> {
        Ok(Self {
            schema_version: 1,
            purpose: "hepta.same-actor-q24-deployment.original-decision.v1",
            phase: phase.to_owned(),
            learning_operation: snapshot.request.operation_id.as_str().to_owned(),
            actual_head: snapshot.head_digest.into_array(),
            original_receipt_signing_bytes: snapshot.receipts.iter()
                .map(learning_iteration_receipt_signing_bytes_v1)
                .collect::<Result<Vec<_>, _>>().map_err(deployment_error)?,
        })
    }
}

//! Immutable Root-approved deployment configuration and late actor data.
//! All signatures, Outcomes, plans, journals and approved materials are real
//! deployment inputs. Missing material has no synthetic or permissive default.

use std::path::PathBuf;
use serde::{Deserialize, Serialize};
use crate::same_actor_q24_deployment_protocol::OriginalDeploymentBinding;
use super::artifacts::{OriginalArtifactDecisionData, OriginalArtifactOwnerData, OriginalSelectionData};
use super::c::OriginalCData;
use super::evaluation::OriginalEvaluationData;
use super::exchange::OriginalActorExchangeData;
use super::files::{MutableFileData, PinnedFileData};
use super::learning::OriginalLearningMaterialsData;
use super::outcome_data::OriginalSignedOutcomeData;
use super::preparation::OriginalPreparationData;
use super::task::{OriginalCircuitData, OriginalInitialData};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalDeploymentData {
    pub schema_version: u32,
    pub binding: OriginalDeploymentBinding,
    pub initial: OriginalInitialData,
    pub task: OriginalCircuitData,
    pub learning: OriginalLearningMaterialsData,
    pub artifacts: OriginalArtifactOwnerData,
    pub authbus_trust: PinnedFileData,
    pub authbus_checkpoint: MutableFileData,
    pub objective_profile: PinnedFileData,
    pub plasticity: PinnedFileData,
    pub objective_a: PinnedFileData,
    pub completion_a: PathBuf,
    pub scoped_material_ready: OriginalActorExchangeData,
    pub independent_training: OriginalActorExchangeData,
    pub artifact_decision: OriginalActorExchangeData,
    pub independent_selection: OriginalActorExchangeData,
    pub current_material_ready: OriginalActorExchangeData,
    pub original_c: OriginalCData,
    pub objective_c: PinnedFileData,
    pub outcome_c: PathBuf,
    pub host_capacity: usize,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalACompletionData {
    pub schema_version: u32,
    pub phase: String,
    pub outcome: OriginalSignedOutcomeData,
    pub preparation: OriginalPreparationData,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalCOutcomeData {
    pub schema_version: u32,
    pub phase: String,
    pub outcome: OriginalSignedOutcomeData,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalEvaluationResponse {
    pub schema_version: u32,
    pub request_digest: [u8; 32],
    pub original: OriginalEvaluationData,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalArtifactResponse {
    pub schema_version: u32,
    pub request_digest: [u8; 32],
    pub original: OriginalArtifactDecisionData,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalSelectionResponse {
    pub schema_version: u32,
    pub request_digest: [u8; 32],
    pub original: OriginalSelectionData,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalMaterialReady {
    pub schema_version: u32,
    pub request_digest: [u8; 32],
    pub material_digest: [u8; 32],
}

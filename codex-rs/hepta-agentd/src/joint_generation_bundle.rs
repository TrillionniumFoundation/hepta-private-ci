//! Assemble a complete unpublished Joint bundle from actual parameter bytes.
//!
//! The caller still authenticates the restored iteration and its original
//! dataset-to-training-input mapping. This pure function checks their content
//! identities, not provenance, current-head freshness, completed training,
//! calibration quality, role signatures, publication or actual model loading.

use codex_hepta_learning_artifacts::CellBundleComponentsV1;
use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_learning_artifacts::CellTrainingLineageV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_neuron::JointGenerationWeightInspectionV1;
use codex_hepta_neuron::inspect_joint_v4_generation_weights_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum JointBundleAssemblyErrorV1 {
    InvalidSnapshot,
    WrongStage,
    CandidateIdentity,
    LineageMismatch,
    InvalidWeights,
    Capacity,
}

impl std::fmt::Display for JointBundleAssemblyErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for JointBundleAssemblyErrorV1 {}

/// A complete descriptor and its actual packet identity. Private fields keep
/// this association immutable; no method creates an owner or a Training receipt.
#[derive(Clone, Debug, PartialEq)]
pub struct UnpublishedJointV4BundleV1 {
    bundle: CellCompatibilityBundleV1,
    weights: JointGenerationWeightInspectionV1,
    iteration_head: Digest32,
}

impl UnpublishedJointV4BundleV1 {
    pub fn bundle(&self) -> &CellCompatibilityBundleV1 {
        &self.bundle
    }

    pub fn physical_weights_digest(&self) -> Digest32 {
        self.weights.physical_weights_digest()
    }

    /// Physical weights packet only; not a full job or publication cost.
    pub fn weights_bytes(&self) -> u64 {
        self.weights.weights_bytes()
    }

    pub fn decoded_weights_digest(&self) -> Digest32 {
        self.weights.decoded_weights_digest()
    }

    pub fn iteration_head(&self) -> Digest32 {
        self.iteration_head
    }

    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

/// Assemble only the successor currently awaiting Training. The original
/// snapshot supplies the predecessor, frozen Dataset and evaluation profile;
/// `lineage.update_rule` must come from the caller's original admitted job.
/// No missing lineage is invented, and the existing snapshot is never advanced.
/// The trainer must separately reconcile its real job, preserve actual metrics
/// and obtain the original owner's signature before recording a Training stage.
pub fn assemble_joint_v4_training_bundle_v1(
    snapshot: &LearningIterationSnapshotV1,
    candidate_artifact_id: StableId,
    lineage: CellTrainingLineageV1,
    weight_packet: &[u8],
) -> Result<UnpublishedJointV4BundleV1, JointBundleAssemblyErrorV1> {
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())
        .map_err(|_| JointBundleAssemblyErrorV1::InvalidSnapshot)?;
    if coordinator.next_stage() != Some(LearningIterationStageV1::Training) {
        return Err(JointBundleAssemblyErrorV1::WrongStage);
    }
    let request = &snapshot.request;
    let selected = request
        .selected_bundle
        .digest()
        .map_err(|_| JointBundleAssemblyErrorV1::InvalidSnapshot)?;
    let Some(LearningIterationObservationV1::Dataset {
        snapshot_digest, ..
    }) = snapshot.receipts.last().map(|receipt| &receipt.observation)
    else {
        return Err(JointBundleAssemblyErrorV1::WrongStage);
    };
    if candidate_artifact_id == request.selected_bundle.artifact_id {
        return Err(JointBundleAssemblyErrorV1::CandidateIdentity);
    }
    if lineage.source_bundle != selected
        || lineage.dataset != *snapshot_digest
        || lineage.evaluation_profile != request.evaluation_profile
        || lineage.update_rule.is_zero()
    {
        return Err(JointBundleAssemblyErrorV1::LineageMismatch);
    }
    if weight_packet.len() as u64 > request.budget.maximum_artifact_bytes {
        return Err(JointBundleAssemblyErrorV1::Capacity);
    }
    let weights = inspect_joint_v4_generation_weights_v1(weight_packet)
        .map_err(|_| JointBundleAssemblyErrorV1::InvalidWeights)?;
    let c = weights.components();
    let bundle = CellCompatibilityBundleV1 {
        artifact_id: candidate_artifact_id,
        generation: request
            .selected_bundle
            .generation
            .next()
            .map_err(|_| JointBundleAssemblyErrorV1::CandidateIdentity)?,
        components: CellBundleComponentsV1 {
            base: c.base,
            organ_adapter: c.organ_adapter,
            cell_adapter: c.cell_adapter,
            heads: c.heads,
            composition: c.composition,
            encoder: c.encoder,
            tokenizer: c.tokenizer,
            normalizer: c.normalizer,
            calibration: c.calibration,
            numeric_profile: c.numeric_profile,
            output_schema: c.output_schema,
            state_schema: c.state_schema,
            state_semantics: c.state_semantics,
        },
        training_lineage: Some(lineage),
        rollback_predecessor: Some(selected),
    };
    bundle
        .digest()
        .map_err(|_| JointBundleAssemblyErrorV1::LineageMismatch)?;
    Ok(UnpublishedJointV4BundleV1 {
        bundle,
        weights,
        iteration_head: snapshot.head_digest,
    })
}

#[cfg(test)]
#[path = "joint_generation_bundle_tests.rs"]
mod tests;

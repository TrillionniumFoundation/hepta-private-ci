//! Explicit evaluated Version host construction from original owner custody.
//! Cold inputs contain opaque original receipts and already-held C owners.

use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;

use super::super::Error;
use super::super::OriginalCircuitRetainedTaskInputsV1;
use super::super::RetainedVersionOriginV1;
use super::super::c_task::RetainedVersionInstalledTaskV1;
use super::super::profile::VersionPurpose;
use super::OriginalCircuitRetainedArtifactCheckpointV1;
use super::OriginalCircuitRetainedVersionHostV1;
use super::RetainedVersionArtifactOwnerV1;
use super::RetainedVersionHostPhaseV1;
use super::RetainedVersionHostStateV1;
use super::RetainedVersionInputsV1;
use crate::AgentdIdentity;
use crate::AgentdUnixFinalUseGrantProvider;
use crate::CircuitTaskSourceReadbackV1;
use crate::NeuronGenerationCurrentOwnerV1;
use crate::OriginalCellEvaluationCommandConnectionV1;
use crate::OriginalCellQ24DatasetCommandReadbackV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24TrainingCommandConnectionV1;
use crate::OriginalCircuitEvaluatedRetentionContextV1;
use crate::PublishedCircuitCellOwnerV1;

pub struct OriginalCircuitEvaluatedVersionRecoveryV1 {
    pub dataset: OriginalCellQ24MaterialCommandReceiptV1,
    pub evaluation: OriginalCircuitEvaluatedRetentionContextV1,
    pub intent_digest: Digest32,
    pub cell: PublishedCircuitCellOwnerV1<FileAnchorWitnessStore>,
    pub source: Arc<CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>>,
    pub identity: AgentdIdentity,
    pub current: Arc<NeuronGenerationCurrentOwnerV1>,
    pub artifacts: Arc<Mutex<LearningArtifactOwnerService>>,
    pub artifact_checkpoint: OriginalCircuitRetainedArtifactCheckpointV1,
    pub artifact_selection: SignedArtifactSelectionV1,
    pub artifact_verifier: ArtifactSelectionVerifierV1,
}

pub(super) struct EvaluatedVersionExpectedV1 {
    pub(super) dataset: OriginalCellQ24MaterialCommandReceiptV1,
    pub(super) evaluation: OriginalCircuitEvaluatedRetentionContextV1,
}

impl OriginalCircuitRetainedVersionHostV1 {
    pub fn from_original_evaluated_owners(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        dataset: OriginalCellQ24DatasetCommandReadbackV1,
        trainer: OriginalCellQ24TrainingCommandConnectionV1,
        evaluator: OriginalCellEvaluationCommandConnectionV1,
        inputs: RetainedVersionInputsV1,
        task: OriginalCircuitRetainedTaskInputsV1,
        artifact_checkpoint: OriginalCircuitRetainedArtifactCheckpointV1,
        final_use_issuer: AgentdUnixFinalUseGrantProvider,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        let started = super::super::now()?;
        let (initial_binding, at) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)?;
        super::super::require_clock(started, at)?;
        OriginalCellQ24DatasetCommandReadbackV1::require_initial_context(&dataset, &material)?;
        task.require_completed_a(&inputs.completed)?;
        let artifacts = RetainedVersionArtifactOwnerV1::new(
            Arc::clone(&inputs.authorities.artifacts),
            artifact_checkpoint,
            inputs.selection.signed.clone(),
            inputs.selection.verifier.clone(),
        )?;
        let control = Arc::clone(&inputs.current);
        let final_use_issuer =
            AgentdUnixFinalUseGrantProvider::into_original_retained_version_issuer(
                final_use_issuer,
            )?;
        let phase = RetainedVersionHostPhaseV1::Awaiting {
            inputs: Box::new(inputs),
            task,
        };
        Self::new(
            material,
            initial_binding,
            RetainedVersionOriginV1::Fresh,
            VersionPurpose::Evaluated,
            RetainedVersionHostStateV1 {
                dataset,
                initial_trainer: Some(trainer),
                trainer: None,
                initial_evaluator: Some(evaluator),
                evaluator: None,
                shared_evaluated: None,
                cut: None,
                expected: None,
                expected_evaluated: None,
                control,
                artifacts,
                final_use_issuer: Some(final_use_issuer),
                phase: Some(phase),
                selection_reader: None,
            },
            lifetime,
        )
    }

    pub fn recover_from_original_evaluated_owners(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        dataset: OriginalCellQ24DatasetCommandReadbackV1,
        trainer: OriginalCellQ24TrainingCommandConnectionV1,
        evaluator: OriginalCellEvaluationCommandConnectionV1,
        original: OriginalCircuitEvaluatedVersionRecoveryV1,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        let (initial_binding, _) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)?;
        OriginalCellQ24DatasetCommandReadbackV1::require_initial_context(&dataset, &material)?;
        OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
            &original.dataset,
            &material,
        )?;
        let evaluation = original.evaluation.into_original_receipt_readback();
        evaluation.original_receipt_predecessors(super::super::now()?)?;
        if original.intent_digest.is_zero() || evaluation.snapshot().receipts.len() != 4 {
            return Err(Error::Binding("original evaluated Version recovery cut"));
        }
        let artifacts = RetainedVersionArtifactOwnerV1::new(
            original.artifacts,
            original.artifact_checkpoint,
            original.artifact_selection,
            original.artifact_verifier,
        )?;
        let phase = RetainedVersionHostPhaseV1::Recovered(RetainedVersionInstalledTaskV1 {
            cell: original.cell,
            source: original.source,
            identity: original.identity,
            intent: original.intent_digest,
        });
        Self::new(
            material,
            initial_binding,
            RetainedVersionOriginV1::Recovered,
            VersionPurpose::Evaluated,
            RetainedVersionHostStateV1 {
                dataset,
                initial_trainer: Some(trainer),
                trainer: None,
                initial_evaluator: Some(evaluator),
                evaluator: None,
                shared_evaluated: None,
                cut: None,
                expected: None,
                expected_evaluated: Some(EvaluatedVersionExpectedV1 {
                    dataset: original.dataset,
                    evaluation,
                }),
                control: original.current,
                artifacts,
                final_use_issuer: None,
                phase: Some(phase),
                selection_reader: None,
            },
            lifetime,
        )
    }
}

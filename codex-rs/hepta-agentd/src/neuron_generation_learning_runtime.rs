//! Read-only learning observations through the ordinary bounded generation
//! actor. Only a real Ready publication can bind this view to its journal.

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationIntentV2;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_types::StableId;

use super::GenerationCommand;
use super::NeuronGenerationRuntimeHandleV2;
use crate::AgentdError;
use crate::PublishedNeuronGenerationUpdateV1;
use crate::neuron_generation_update_bootstrap::GenerationLearningReadbackV1;

/// Preserve both bounded actor failures and the original readback rejection.
#[derive(Debug, thiserror::Error)]
pub enum NeuronGenerationLearningReadErrorV1 {
    #[error("generation learning transport: {0}")]
    Runtime(#[from] CellGenerationErrorV2),
    #[error("generation learning observation: {0}")]
    Observation(#[from] AgentdError),
}

pub(crate) enum GenerationLearningReadV1 {
    Selection(Box<LearningIterationCoordinatorV1>),
    NextUse {
        coordinator: Box<LearningIterationCoordinatorV1>,
        intent: CellGenerationIntentV2,
    },
}

pub(crate) enum GenerationLearningPublicationV1 {
    Unpublished,
    Published(PublishedNeuronGenerationUpdateV1),
}

impl GenerationLearningPublicationV1 {
    pub(crate) fn read<W: AnchorWitnessStore>(
        &self,
        journal: &CellGenerationJournalV2<W>,
        request: GenerationLearningReadV1,
    ) -> Result<LearningIterationObservationV1, AgentdError> {
        let Self::Published(publication) = self else {
            return Err(AgentdError::GenerationFenced(
                "generation actor has no original learning publication".into(),
            ));
        };
        let reader = GenerationLearningReadbackV1 {
            journal,
            publication,
        };
        match request {
            GenerationLearningReadV1::Selection(coordinator) => reader.read_selection(&coordinator),
            GenerationLearningReadV1::NextUse {
                coordinator,
                intent,
            } => reader.read_next_use(&coordinator, &intent),
        }
    }
}

impl NeuronGenerationRuntimeHandleV2 {
    /// Read the actual publication's selection from the running journal owner.
    /// The coordinator's principal must use the Cell digest's canonical hex ID.
    /// This observation is not a learning attestation or a Chain checkpoint.
    pub async fn read_learning_selection(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
    ) -> Result<LearningIterationObservationV1, NeuronGenerationLearningReadErrorV1> {
        self.call(|response| GenerationCommand::LearningRead {
            request: Box::new(GenerationLearningReadV1::Selection(Box::new(
                coordinator.clone(),
            ))),
            response,
        })
        .await?
        .map_err(Into::into)
    }

    /// Read the original committed intent after real work by this same actor.
    /// No use hash, cutover hash, replacement journal or writer is accepted.
    pub async fn read_learning_next_use(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
        intent: &CellGenerationIntentV2,
    ) -> Result<LearningIterationObservationV1, NeuronGenerationLearningReadErrorV1> {
        StableId::new(&intent.operation_id).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        self.call(|response| GenerationCommand::LearningRead {
            request: Box::new(GenerationLearningReadV1::NextUse {
                coordinator: Box::new(coordinator.clone()),
                intent: intent.clone(),
            }),
            response,
        })
        .await?
        .map_err(Into::into)
    }
}

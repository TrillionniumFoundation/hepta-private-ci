//! Private custody of the original publication preparation. Every variant is
//! consumed once, retaining the same original finite predecessor connections.

use codex_hepta_contracts::{FinalUseBinding, SignedFinalUseGrant};
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;

use super::super::Error;
use crate::{OriginalCellEvaluationCommandClientV1, OriginalCellQ24TrainingCommandClientV1};
use crate::{PreparedOriginalCircuitEvaluatedRetentionV1, PreparedOriginalCircuitRetainedPublicationV1};
use crate::PublishedCircuitFeatureTaskV1;

pub(super) enum RetainedVersionPreparedV1 {
    TrainingNoUpdate(PreparedOriginalCircuitRetainedPublicationV1<FileAnchorWitnessStore, FileAnchorWitnessStore>),
    EvaluatedNoUpdate(PreparedOriginalCircuitEvaluatedRetentionV1<FileAnchorWitnessStore, FileAnchorWitnessStore>),
}

impl RetainedVersionPreparedV1 {
    pub(super) fn final_use_binding(&self) -> &FinalUseBinding {
        match self {
            Self::TrainingNoUpdate(original) => original.final_use_binding(),
            Self::EvaluatedNoUpdate(original) => original.final_use_binding(),
        }
    }

    pub(super) fn intent_digest(&self) -> Digest32 {
        match self {
            Self::TrainingNoUpdate(original) => original.intent_digest(),
            Self::EvaluatedNoUpdate(original) => original.intent_digest(),
        }
    }

    pub(super) fn completed(&self) -> &crate::PublishedCircuitFeatureCompletionV1 {
        match self {
            Self::TrainingNoUpdate(original) => &original.completed,
            Self::EvaluatedNoUpdate(original) => &original.completed,
        }
    }

    pub(super) fn trainer(&self) -> &OriginalCellQ24TrainingCommandClientV1 {
        match self {
            Self::TrainingNoUpdate(original) => &original.trainer,
            Self::EvaluatedNoUpdate(original) => &original.trainer,
        }
    }

    pub(super) fn evaluator(&self) -> Option<&OriginalCellEvaluationCommandClientV1> {
        match self {
            Self::TrainingNoUpdate(_) => None,
            Self::EvaluatedNoUpdate(original) => Some(&original.evaluator),
        }
    }

    pub(super) async fn publish(
        self,
        signed: SignedFinalUseGrant,
    ) -> Result<(PublishedCircuitFeatureTaskV1, OriginalCellQ24TrainingCommandClientV1,
        Option<OriginalCellEvaluationCommandClientV1>), Error> {
        match self {
            Self::TrainingNoUpdate(original) => {
                let (task, trainer) = PreparedOriginalCircuitRetainedPublicationV1::publish_and_retain_original_trainer(
                    original,
                    signed,
                )
                .await?;
                Ok((task, trainer, None))
            }
            Self::EvaluatedNoUpdate(original) => {
                let (task, trainer, evaluator) = PreparedOriginalCircuitEvaluatedRetentionV1::publish_and_retain_original_evidence(
                    original,
                    signed,
                )
                .await?;
                Ok((task, trainer, Some(evaluator)))
            }
        }
    }
}

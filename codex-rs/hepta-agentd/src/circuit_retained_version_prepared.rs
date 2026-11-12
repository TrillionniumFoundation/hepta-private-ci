//! The same one-shot preparation, with explicit legacy/evaluated custody.

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;

use super::super::super::context::PublicationAccess;
use super::super::Error;
use super::super::profile::VersionCut;
use crate::OriginalCellEvaluationCommandClientV1;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::PreparedOriginalCircuitEvaluatedRetentionV1;
use crate::PreparedOriginalCircuitRetainedPublicationV1;
use crate::PublishedCircuitFeatureCompletionV1;
use crate::PublishedCircuitFeatureTaskV1;

pub(super) enum RetainedVersionPreparedV1 {
    TrainingNoUpdate(
        Box<
            PreparedOriginalCircuitRetainedPublicationV1<
                FileAnchorWitnessStore,
                FileAnchorWitnessStore,
            >,
        >,
    ),
    Evaluated(
        Box<
            PreparedOriginalCircuitEvaluatedRetentionV1<
                FileAnchorWitnessStore,
                FileAnchorWitnessStore,
            >,
        >,
    ),
}

impl RetainedVersionPreparedV1 {
    pub(super) fn intent_digest(&self) -> Digest32 {
        match self {
            Self::TrainingNoUpdate(original) => original.intent_digest(),
            Self::Evaluated(original) => original.intent_digest(),
        }
    }

    pub(super) fn final_use_binding(&self) -> &FinalUseBinding {
        match self {
            Self::TrainingNoUpdate(original) => original.final_use_binding(),
            Self::Evaluated(original) => original.final_use_binding(),
        }
    }

    pub(super) fn completed(&self) -> &PublishedCircuitFeatureCompletionV1 {
        match self {
            Self::TrainingNoUpdate(original) => &original.completed,
            Self::Evaluated(original) => original.original_completed_for_version(),
        }
    }

    pub(super) async fn require_current(&self, cut: &VersionCut) -> Result<(), Error> {
        match (self, cut) {
            (Self::TrainingNoUpdate(original), VersionCut::TrainingNoUpdate(cut)) => Ok(cut
                .training
                .require_training_current(&original.trainer, PublicationAccess::Readback)
                .await?),
            (Self::Evaluated(original), VersionCut::Evaluated(cut)) => Ok(original
                .require_current_for_original_version(&cut.evaluated)
                .await?),
            _ => Err(Error::Binding("same original prepared Version purpose")),
        }
    }

    pub(super) async fn publish(
        self,
        signed: SignedFinalUseGrant,
    ) -> Result<
        (
            PublishedCircuitFeatureTaskV1,
            OriginalCellQ24TrainingCommandClientV1,
            Option<OriginalCellEvaluationCommandClientV1>,
        ),
        Error,
    > {
        match self {
            Self::TrainingNoUpdate(original) => {
                let (task, trainer) = PreparedOriginalCircuitRetainedPublicationV1::publish_and_retain_original_trainer(
                    *original, signed,
                ).await?;
                Ok((task, trainer, None))
            }
            Self::Evaluated(original) => {
                let (task, trainer, evaluator) = PreparedOriginalCircuitEvaluatedRetentionV1::publish_and_retain_original_evidence(
                    *original, signed,
                ).await?;
                Ok((task, trainer, Some(evaluator)))
            }
        }
    }
}

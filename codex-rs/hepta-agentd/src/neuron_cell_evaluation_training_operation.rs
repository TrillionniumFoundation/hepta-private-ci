//! A private observation spanning one original Evaluator operation. Only the
//! consuming shared-Trainer host constructs it, after a real original read.
//! It is neither a transferable lease nor a replacement for any panel owner.

use std::sync::Arc;

use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;

use super::contract::Context;
use super::Error;
use crate::LearningIterationEvidenceClientV1;
use crate::OriginalCellEvaluationQualificationConfigV1;
use crate::OriginalCellEvaluationQualificationErrorV1;
use crate::OriginalCellEvaluationReceiptConfigV1;
use crate::OriginalCellEvaluationReceiptErrorV1;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;

/// No public constructor, Clone, serialization or retained storage exists.
pub(crate) struct TrainingOperation {
    trainer: Arc<LearningIterationEvidenceClientV1>,
    context: Context,
}

#[derive(Clone, Copy)]
pub(crate) enum TrainingRead<'a> {
    Independent,
    Operation(&'a TrainingOperation),
}

impl TrainingOperation {
    pub(super) async fn begin(
        trainer: Arc<LearningIterationEvidenceClientV1>,
        context: &Context,
    ) -> Result<Self, Error> {
        let original = Self {
            trainer,
            context: context.clone(),
        };
        original.read_original().await?;
        Ok(original)
    }

    /// Consume the observation before the host's final journal read and fresh
    /// authentication. A failed tail cannot be retried with this observation.
    pub(super) async fn finish(self) -> Result<(), Error> {
        self.read_original().await
    }

    async fn read_original(&self) -> Result<(), Error> {
        let receipt = self
            .context
            .training
            .receipts
            .last()
            .ok_or(Error::Binding("original operation Training cut"))?;
        let actual = LearningIterationEvidenceClientV1::readback(
            self.trainer.as_ref(),
            &self.context.training,
            receipt,
        )
            .await
            .map_err(OriginalCellEvaluationQualificationErrorV1::from)?;
        if actual != self.context.training_evidence {
            return Err(Error::Binding("changed original operation Training signature"));
        }
        Ok(())
    }

    pub(crate) fn require_member(
        &self,
        trainer: &Arc<LearningIterationEvidenceClientV1>,
        config: &OriginalCellEvaluationQualificationConfigV1,
    ) -> Result<(), OriginalCellEvaluationQualificationErrorV1> {
        if !Arc::ptr_eq(&self.trainer, trainer) {
            return Err(OriginalCellEvaluationQualificationErrorV1::Binding(
                "same actual operation Trainer connection",
            ));
        }
        TrainingOperation::require_qualification(self, trainer.as_ref(), config)
    }

    pub(crate) fn require_qualification(
        &self,
        trainer: &LearningIterationEvidenceClientV1,
        config: &OriginalCellEvaluationQualificationConfigV1,
    ) -> Result<(), OriginalCellEvaluationQualificationErrorV1> {
        if !std::ptr::eq(self.trainer.as_ref(), trainer)
            || config.training != self.context.training
            || config.training_evidence != self.context.training_evidence
            || config.scope != self.context.scope
            || config.verifier.trust_digest() != self.context.verifier.trust_digest()
            || config.verifier.scope_digest() != self.context.verifier.scope_digest()
            || config.verifier.objective_digest() != self.context.verifier.objective_digest()
        {
            return Err(OriginalCellEvaluationQualificationErrorV1::Binding(
                "same complete original operation Training and verifier",
            ));
        }
        Ok(())
    }
}

impl TrainingRead<'_> {
    pub(crate) async fn receipt_evidence(
        self,
        trainer: &LearningIterationEvidenceClientV1,
        snapshot: &LearningIterationSnapshotV1,
        config: &OriginalCellEvaluationReceiptConfigV1,
    ) -> Result<SignedLearningEvidenceV1, OriginalCellEvaluationReceiptErrorV1> {
        let receipt = config
            .training
            .receipts
            .last()
            .ok_or(LearningOriginalOwnerErrorV1::Binding("original Training cut"))?;
        match self {
            Self::Independent => Ok(
                LearningIterationEvidenceClientV1::readback(trainer, snapshot, receipt).await?,
            ),
            Self::Operation(original) => {
                if !std::ptr::eq(original.trainer.as_ref(), trainer)
                    || snapshot != &original.context.training
                    || config.training != original.context.training
                    || config.scope != original.context.scope
                    || config.signing.verifier.trust_digest()
                        != original.context.verifier.trust_digest()
                    || config.signing.verifier.scope_digest()
                        != original.context.verifier.scope_digest()
                    || config.signing.verifier.objective_digest()
                        != original.context.verifier.objective_digest()
                {
                    return Err(LearningOriginalOwnerErrorV1::Binding(
                        "same original operation receipt Trainer and full context",
                    )
                    .into());
                }
                Ok(original.context.training_evidence.clone())
            }
        }
    }
}

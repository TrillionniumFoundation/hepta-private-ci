//! A local, sealed view of the original published Version's same T/E channels.
//! It has no new-work method, owner factory, descriptor or reconnect interface.

use std::sync::Arc;

use super::OriginalCircuitRetainedVersionHostV1;
use super::RetainedVersionFinalUseOutcomeV1;
use super::RetainedVersionHostPhaseV1;
use super::super::Error;
use super::super::RetainedVersionOriginV1;
use super::super::RetainedVersionPurposeV1;
use crate::OriginalCellEvaluationCommandClientV1;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::OriginalCircuitEvaluatedRetentionContextV1;
use crate::OriginalCircuitRetainedPublicationErrorV1;

pub struct OriginalCircuitPublishedEvidenceReadbackV1 {
    trainer: Arc<OriginalCellQ24TrainingCommandClientV1>,
    evaluator: Arc<OriginalCellEvaluationCommandClientV1>,
    context: OriginalCircuitEvaluatedRetentionContextV1,
}

impl Clone for OriginalCircuitPublishedEvidenceReadbackV1 {
    fn clone(&self) -> Self {
        Self {
            trainer: Arc::clone(&self.trainer),
            evaluator: Arc::clone(&self.evaluator),
            context: self.context.clone_for_original_receipt(),
        }
    }
}

impl OriginalCircuitPublishedEvidenceReadbackV1 {
    /// Perform actual original T/E reads. This is not a cached publication
    /// result or a new-work capability. Competing reads retain the original
    /// Unavailable/Unknown semantics; sharing creates no queue or retry.
    pub async fn read_original_predecessors(&self) -> Result<(), Error> {
        self.context
            .require_original_receipt_owners(self.trainer.as_ref(), self.evaluator.as_ref())
            .await?;
        Ok(())
    }

    pub(crate) fn require_original_context(
        &self,
        expected: &OriginalCircuitEvaluatedRetentionContextV1,
    ) -> Result<(), OriginalCircuitRetainedPublicationErrorV1> {
        if self.context.snapshot() != expected.snapshot()
            || self.context.receipt_context_binding() != expected.receipt_context_binding()
        {
            return Err(OriginalCircuitRetainedPublicationErrorV1::Binding(
                "same original published T/E context",
            ));
        }
        let at = super::super::super::now()?;
        self.context.original_receipt_predecessors(at)?;
        expected.original_receipt_predecessors(at)?;
        Ok(())
    }

    pub(crate) fn original_clients(
        &self,
    ) -> (&OriginalCellQ24TrainingCommandClientV1, &OriginalCellEvaluationCommandClientV1) {
        (self.trainer.as_ref(), self.evaluator.as_ref())
    }
}

impl OriginalCircuitRetainedVersionHostV1 {
    /// Consume the already retained clients only after actual Published and a
    /// full current read. A cold Published enum alone does not admit a reader.
    /// All aliases keep the original clients' one channel slot and lifetime.
    pub async fn share_original_evaluated_readbacks(
        self: Arc<Self>,
    ) -> Result<OriginalCircuitPublishedEvidenceReadbackV1, Error> {
        tokio::task::spawn_blocking(move || {
            self.require_lifetime()?;
            if self.purpose != RetainedVersionPurposeV1::EvaluatedNoUpdate
                || self.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Published
            {
                return Err(Error::ReadbackRequired);
            }
            let mut state = self.state.try_lock().map_err(|_| Error::Busy)?;
            if let Err(error) = self.bind_original_predecessor(&mut state) {
                if self.origin == RetainedVersionOriginV1::Recovered {
                    state.selection_reader = None;
                }
                return Err(error);
            }
            let observed = if self.origin == RetainedVersionOriginV1::Recovered {
                self.read_original_recovery(&mut state)?
            } else {
                self.read_original(&state)?
            };
            if observed.publication().is_none()
                || state.selection_reader.is_none()
                || !matches!(
                    state.phase.as_ref(),
                    Some(RetainedVersionHostPhaseV1::Installed { .. } | RetainedVersionHostPhaseV1::Recovered(_))
                )
                || self.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Published
            {
                return Err(Error::ReadbackRequired);
            }
            let context = state.cut.as_ref().and_then(|cut| cut.evaluated.as_ref())
                .ok_or(Error::ReadbackRequired)?.clone_for_original_receipt();
            if state.shared_evaluated.is_none() {
                let original = match (state.trainer.take(), state.evaluator.take()) {
                    (Some(trainer), Some(evaluator)) => (trainer, evaluator),
                    _ => {
                        state.selection_reader = None;
                        return Err(Error::Unavailable);
                    }
                };
                let (trainer, evaluator) = match context.seal_original_readback_owners(original.0, original.1) {
                    Ok(value) => value,
                    Err(error) => {
                        state.selection_reader = None;
                        return Err(error.into());
                    }
                };
                state.shared_evaluated = Some(OriginalCircuitPublishedEvidenceReadbackV1 {
                    trainer,
                    evaluator,
                    context: context.clone_for_original_receipt(),
                });
            }
            let shared = state.shared_evaluated.as_ref().ok_or(Error::Unavailable)?;
            shared.require_original_context(&context)?;
            self.require_lifetime()?;
            Ok(shared.clone())
        }).await.map_err(|_| Error::CommitUncertain)?
    }
}

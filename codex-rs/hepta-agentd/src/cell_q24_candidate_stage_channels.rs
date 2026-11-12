//! One-way transfer of the already admitted original channels to the completed
//! evaluated NoUpdate continuation. This child can consume private slots but
//! offers no channel getter, replacement constructor or caller-chosen origin.

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1 as Stage;

use super::super::candidate::retention::EvaluatedChannels;
use super::Continuation;
use super::Error;
use super::Owners;

impl Continuation {
    pub(in super::super) fn take_original_evaluated_channels(
        &mut self,
        owners: &Owners,
        evaluation: &crate::OriginalCellEvaluationCommandReceiptV1,
    ) -> Result<EvaluatedChannels, Error> {
        use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
        use codex_hepta_learning_artifacts::LearningIterationObservationV1;

        let dataset = self
            .original_dataset
            .as_ref()
            .ok_or(Error::CommitUncertain)?;
        let training = self
            .original_training
            .as_ref()
            .ok_or(Error::CommitUncertain)?;
        let snapshot = evaluation.snapshot();
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
        owners.material.scope.validate_snapshot(snapshot)?;
        if snapshot.request != owners.material.initial.request
            || snapshot.owners != owners.material.initial.owners
            || snapshot.receipts.len() != 4
            || snapshot.training_no_update_v2().is_some()
            || coordinator.candidate().is_none()
            || coordinator.next_stage() != Some(Stage::Selection)
            || !snapshot.receipts.starts_with(&dataset.snapshot().receipts)
            || snapshot.receipts.get(2) != Some(training.receipt())
            || evaluation.training_attestation() != training.attestation()
            || !matches!(
                evaluation.receipt().observation,
                LearningIterationObservationV1::Evaluation {
                    disposition: LearningEvaluationDispositionV1::NoUpdate,
                    ..
                }
            )
            || self.version.is_some()
            || self.selector.is_some()
            || self.next_use.is_some()
            || self.readiness.is_some()
            || self.original_selection.is_some()
        {
            return Err(Error::WrongScope);
        }
        // Every take is one-way. A partial failure drops the moved capabilities;
        // it never restores a slot, reopens a peer or changes the original end.
        Ok(EvaluatedChannels {
            version: self.version_initial.take().ok_or(Error::CommitUncertain)?,
            selector: self.selector_initial.take().ok_or(Error::CommitUncertain)?,
            next_use: self.next_use_initial.take().ok_or(Error::CommitUncertain)?,
            readiness: self
                .readiness_initial
                .take()
                .ok_or(Error::CommitUncertain)?,
        })
    }
}

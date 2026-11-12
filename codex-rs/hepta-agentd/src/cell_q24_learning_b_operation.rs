//! All B-dependent checks in one owner operation borrow one actual Root
//! observation. A second Root read must match after work, including failure.
//! The observation is owned only by this stack frame, never by the aggregate.

use super::*;

impl OriginalQ24StageOperationV1<'_, '_, '_, '_> {
    pub(super) fn require_original_b_read(&mut self) -> Result<(), Error> {
        if self.original_b.is_none() {
            let original =
                OriginalQ24TrainingOperationV1::read_original_training_evidence(self.training)?;
            let observed = self.owners.complete_original_root_evaluation(
                &original,
                self.inner.prepared.scope(),
                OriginalRootBEvaluationActionV1::Readback,
            )?;
            self.original_b = Some(observed);
        }
        Ok(())
    }

    pub(super) fn finish_original_b_read(&mut self) -> Result<(), Error> {
        let Some(before) = self.original_b.take() else {
            return Ok(());
        };
        let original =
            OriginalQ24TrainingOperationV1::read_original_training_evidence(self.training)?;
        let after = self.owners.complete_original_root_evaluation(
            &original,
            self.inner.prepared.scope(),
            OriginalRootBEvaluationActionV1::Readback,
        )?;
        if !before.same_original_observation(&after) {
            return Err(Error::CommitUncertain);
        }
        Ok(())
    }

    pub(super) fn model_root_action(
        &mut self,
        snapshot: &LearningIterationSnapshotV1,
        action: model::Action,
    ) -> Result<(LearningIterationReceiptV1, Option<SignedLearningEvidenceV1>), Error> {
        self.require_original_b_read()?;
        let original =
            OriginalQ24TrainingOperationV1::read_original_training_evidence(self.training)?;
        let observed = self.original_b.as_ref().ok_or(Error::CommitUncertain)?;
        self.owners.model_root_action_from_original_b(
            self.inner,
            self.runtime,
            &original,
            observed,
            snapshot,
            action,
        )
    }

    pub(super) fn read_publication_material(
        &mut self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<Option<codex_hepta_neuron::CellBackendManifestV2>, Error> {
        self.inner.require_snapshot(snapshot)?;
        for receipt in &snapshot.receipts {
            self.authenticate_receipt(snapshot, receipt)?;
        }
        let adopts = matches!(snapshot.receipts.last().map(|receipt| &receipt.observation),
            Some(LearningIterationObservationV1::LocalDecisionV2(decision))
                if decision.disposition == codex_hepta_learning_artifacts::LearningLocalDispositionV2::AdoptCandidate);
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
        if coordinator.next_task_bundle().is_none()
            || adopts
                != coordinator
                    .next_task_bundle()
                    .is_some_and(|bundle| bundle != &snapshot.request.selected_bundle)
        {
            return Err(Error::WrongScope);
        }
        if !adopts {
            return Ok(None);
        }
        self.require_original_b_read()?;
        let observed = self.original_b.as_ref().ok_or(Error::CommitUncertain)?;
        Ok(Some(observed.manifest().clone()))
    }
}

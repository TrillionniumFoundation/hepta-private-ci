//! Original evaluated C attestation over the same remote published-task owner.
//! Read-only T/B/S capabilities do not grant task execution or a new signature.

use super::*;

pub struct OriginalCircuitEvaluatedNextUseRemoteSourcesV1<'a> {
    pub snapshot: &'a LearningIterationSnapshotV1,
    pub selection: &'a OriginalCircuitEvaluatedSelectionReceiptV1,
    pub live: &'a OriginalCircuitLearningReadClientV1,
    pub trainer: &'a OriginalCellQ24TrainingCommandClientV1,
    pub evaluator: &'a OriginalCellEvaluationCommandClientV1,
    pub selector: &'a LearningIterationEvidenceClientV1,
}

impl NextUseSources for OriginalCircuitEvaluatedNextUseRemoteSourcesV1<'_> {
    fn snapshot(&self) -> &LearningIterationSnapshotV1 { self.snapshot }
    fn trainer(&self) -> Option<&LearningIterationEvidenceClientV1> { None }
    fn selector(&self) -> &LearningIterationEvidenceClientV1 { self.selector }
    fn evaluated_owners(&self) -> Option<(&OriginalCellQ24TrainingCommandClientV1, &OriginalCellEvaluationCommandClientV1)> {
        Some((self.trainer, self.evaluator))
    }
    fn location(&self) -> ObservationLocation {
        // Match the original evaluated owner ordering: final live Source/Cell
        // read follows every awaited T/B/S predecessor read.
        ObservationLocation::EvaluatedOwner
    }

    fn require_profile(&self, profile: &Profile) -> Result<(), Error> {
        let Profile::Evaluated(original) = profile else {
            return Err(OwnerError::Binding("original evaluated remote NextUse profile").into());
        };
        if self.selection.snapshot() != original.snapshot()
            || self.selection.original_receipt_binding() != original.original_receipt_binding()
        {
            return Err(OwnerError::Binding("same original evaluated remote Selection").into());
        }
        self.live.require_original_evaluated_next_use(original)?;
        Ok(())
    }

    async fn observe(&self, _config: &OriginalCircuitNextUseReceiptConfigV1) -> Result<LearningIterationObservationV1, Error> {
        let original = OriginalCircuitLearningReadClientV1::read_current(self.live).await?;
        Ok(original.observation().clone())
    }
}

impl<W: AnchorWitnessStore> OriginalCircuitNextUseReceiptOwnerV1<W> {
    pub(crate) fn original_evaluated_command_selection(&self) -> Option<&OriginalCircuitEvaluatedSelectionReceiptV1> {
        match &self.profile {
            Profile::Legacy => None,
            Profile::Evaluated(selection) => Some(selection),
        }
    }

    pub async fn attest_original_evaluated_remote_completion(
        &mut self, source: OriginalCircuitEvaluatedNextUseRemoteSourcesV1<'_>,
    ) -> Result<OriginalCircuitEvaluatedNextUseReceiptV1, Error> {
        let completed = match self.command_origin {
            CommandOrigin::FreshCreate => self.attest_source(source).await?,
            CommandOrigin::Recovered => self.readback_source(source).await?,
        };
        self.completed_evaluated_next_use(completed)
    }

    pub async fn readback_evaluated_remote_completion(
        &mut self, source: OriginalCircuitEvaluatedNextUseRemoteSourcesV1<'_>,
    ) -> Result<OriginalCircuitEvaluatedNextUseReceiptV1, Error> {
        let completed = self.readback_source(source).await?;
        self.completed_evaluated_next_use(completed)
    }

    pub fn into_evaluated_command_owner(
        self,
        live: OriginalCircuitLearningReadClientV1,
        trainer: OriginalCellQ24TrainingCommandClientV1,
        evaluator: OriginalCellEvaluationCommandClientV1,
        selector: LearningIterationEvidenceClientV1,
    ) -> Result<crate::OriginalCircuitNextUseCommandOwnerV1<W>, crate::OriginalCircuitNextUseCommandErrorV1>
    where W: Send + 'static,
    {
        crate::OriginalCircuitNextUseCommandOwnerV1::from_original_evaluated_receipt_owner(
            self, live, trainer, evaluator, selector)
    }
}

//! Evaluated S consumes the actual purpose-fixed task read capability.
//! The original T/B command owners and S journal remain the same owners;
//! no remotely supplied observation or write-capable Selector enters here.

use super::*;

pub struct OriginalCircuitEvaluatedSelectionRemoteSourcesV1<'a> {
    pub snapshot: &'a LearningIterationSnapshotV1,
    pub live: &'a OriginalCircuitLearningReadClientV1,
    pub trainer: &'a OriginalCellQ24TrainingCommandClientV1,
    pub evaluator: &'a OriginalCellEvaluationCommandClientV1,
}

impl SelectionSources for OriginalCircuitEvaluatedSelectionRemoteSourcesV1<'_> {
    fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        self.snapshot
    }

    fn trainer(&self) -> Option<&LearningIterationEvidenceClientV1> {
        None
    }

    fn evaluated_owners(
        &self,
    ) -> Option<(
        &OriginalCellQ24TrainingCommandClientV1,
        &OriginalCellEvaluationCommandClientV1,
    )> {
        Some((self.trainer, self.evaluator))
    }

    fn location(&self) -> ObservationLocation {
        // The final actual Source and Cell read follows all awaited T/B reads.
        ObservationLocation::EvaluatedOwner
    }

    fn require_profile(&self, profile: &Profile) -> Result<(), Error> {
        let Profile::Evaluated(context) = profile else {
            return Err(OwnerError::Binding("original evaluated remote Selector profile").into());
        };
        self.live.require_original_evaluated_selection(context)?;
        Ok(())
    }

    async fn observe(
        &self,
        _config: &OriginalCircuitSelectionReceiptConfigV1,
    ) -> Result<LearningIterationObservationV1, Error> {
        let original = OriginalCircuitLearningReadClientV1::read_current(self.live).await?;
        Ok(original.observation().clone())
    }
}

impl<W: AnchorWitnessStore> OriginalCircuitSelectionReceiptOwnerV1<W> {
    /// Use the same original custody and journal, with actual task-host reads
    /// around T/B evidence and signing. Recovered owners never claim work.
    pub async fn attest_original_evaluated_remote_selection(
        &mut self,
        source: OriginalCircuitEvaluatedSelectionRemoteSourcesV1<'_>,
    ) -> Result<OriginalCircuitEvaluatedSelectionReceiptV1, Error> {
        let completed = match self.command_origin {
            CommandOrigin::FreshCreate => self.attest_source(source).await?,
            CommandOrigin::Recovered => self.readback_source(source).await?,
        };
        self.completed_evaluated_selection(completed)
    }

    pub async fn readback_evaluated_remote_selection(
        &mut self,
        source: OriginalCircuitEvaluatedSelectionRemoteSourcesV1<'_>,
    ) -> Result<OriginalCircuitEvaluatedSelectionReceiptV1, Error> {
        let completed = self.readback_source(source).await?;
        self.completed_evaluated_selection(completed)
    }
}

//! Actual remote C observations feed the original evaluated Observer journal.
//! Live original T/B and read-only S evidence still bracket the journal; the
//! final task Source/Cell read is after all awaited predecessor readbacks.

use super::*;

use crate::OriginalCircuitLearningReadClientV1;

pub struct OriginalCircuitEvaluatedNextUseRemoteSourcesV1<'a> {
    pub snapshot: &'a LearningIterationSnapshotV1,
    pub live: &'a OriginalCircuitLearningReadClientV1,
    pub trainer: &'a OriginalCellQ24TrainingCommandClientV1,
    pub evaluator: &'a OriginalCellEvaluationCommandClientV1,
    pub selector: &'a LearningIterationEvidenceClientV1,
}

impl NextUseSources for OriginalCircuitEvaluatedNextUseRemoteSourcesV1<'_> {
    fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        self.snapshot
    }

    fn trainer(&self) -> Option<&LearningIterationEvidenceClientV1> {
        None
    }

    fn selector(&self) -> &LearningIterationEvidenceClientV1 {
        self.selector
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
        ObservationLocation::EvaluatedOwner
    }

    fn require_profile(&self, profile: &Profile) -> Result<(), Error> {
        let Profile::Evaluated(selection) = profile else {
            return Err(OwnerError::Binding("original evaluated remote C profile").into());
        };
        self.live.require_original_evaluated_next_use(selection)?;
        Ok(())
    }

    async fn observe(
        &self,
        _config: &OriginalCircuitNextUseReceiptConfigV1,
    ) -> Result<LearningIterationObservationV1, Error> {
        let original = OriginalCircuitLearningReadClientV1::read_current(self.live).await?;
        Ok(original.observation().clone())
    }
}

impl<W: AnchorWitnessStore> OriginalCircuitNextUseReceiptOwnerV1<W> {
    pub async fn attest_original_evaluated_remote_completion(
        &mut self,
        source: OriginalCircuitEvaluatedNextUseRemoteSourcesV1<'_>,
    ) -> Result<OriginalCircuitEvaluatedNextUseReceiptV1, Error> {
        let completed = match self.command_origin {
            CommandOrigin::FreshCreate => self.attest_source(source).await?,
            CommandOrigin::Recovered => self.readback_source(source).await?,
        };
        self.completed_evaluated_next_use(completed)
    }

    pub async fn readback_evaluated_remote_completion(
        &mut self,
        source: OriginalCircuitEvaluatedNextUseRemoteSourcesV1<'_>,
    ) -> Result<OriginalCircuitEvaluatedNextUseReceiptV1, Error> {
        let completed = self.readback_source(source).await?;
        self.completed_evaluated_next_use(completed)
    }
}

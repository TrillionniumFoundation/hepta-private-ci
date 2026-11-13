//! The concrete local Selector source retains the original read protocol.
//! Its additional same-Version/same-T/E checks do not alter remote admission.

use super::*;

/// Concrete local source: delegate the unchanged original read protocol and
/// additionally bind every preparation to the same Version-owned T/E pair.
pub(crate) struct OriginalCircuitEvaluatedSelectionLocalSourcesV1<'a> {
    pub(crate) original: OriginalCircuitEvaluatedSelectionRemoteSourcesV1<'a>,
    pub(crate) shared: &'a crate::OriginalCircuitPublishedEvidenceReadbackV1,
}

impl SelectionSources for OriginalCircuitEvaluatedSelectionLocalSourcesV1<'_> {
    fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        SelectionSources::snapshot(&self.original)
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
        SelectionSources::evaluated_owners(&self.original)
    }

    fn location(&self) -> ObservationLocation {
        ObservationLocation::EvaluatedOwner
    }

    fn require_profile(&self, profile: &Profile) -> Result<(), Error> {
        SelectionSources::require_profile(&self.original, profile)?;
        let Profile::Evaluated(context) = profile else {
            return Err(OwnerError::Binding("original local evaluated Selector profile").into());
        };
        OriginalCircuitLearningReadClientV1::require_original_local_evaluated_selection(
            self.original.live, context,
        )?;
        OriginalCircuitLearningReadClientV1::require_original_local_shared_readbacks(
            self.original.live, self.shared,
        )?;
        crate::OriginalCircuitPublishedEvidenceReadbackV1::require_original_context(
            self.shared, context,
        )?;
        let (trainer, evaluator) =
            crate::OriginalCircuitPublishedEvidenceReadbackV1::original_clients(self.shared);
        if !std::ptr::eq(trainer, self.original.trainer)
            || !std::ptr::eq(evaluator, self.original.evaluator)
        {
            return Err(OwnerError::Binding("same original local Selector T/E sources").into());
        }
        Ok(())
    }

    async fn observe(
        &self,
        config: &OriginalCircuitSelectionReceiptConfigV1,
    ) -> Result<LearningIterationObservationV1, Error> {
        SelectionSources::observe(&self.original, config).await
    }
}

impl<W: AnchorWitnessStore> OriginalCircuitSelectionReceiptOwnerV1<W> {
    pub(crate) async fn attest_original_evaluated_local_selection(
        &mut self,
        source: OriginalCircuitEvaluatedSelectionLocalSourcesV1<'_>,
    ) -> Result<OriginalCircuitEvaluatedSelectionReceiptV1, Error> {
        let completed = match self.command_origin {
            CommandOrigin::FreshCreate => self.attest_source(source).await?,
            CommandOrigin::Recovered => self.readback_source(source).await?,
        };
        self.completed_evaluated_selection(completed)
    }

    pub(crate) async fn readback_evaluated_local_selection(
        &mut self,
        source: OriginalCircuitEvaluatedSelectionLocalSourcesV1<'_>,
    ) -> Result<OriginalCircuitEvaluatedSelectionReceiptV1, Error> {
        let completed = self.readback_source(source).await?;
        self.completed_evaluated_selection(completed)
    }
}

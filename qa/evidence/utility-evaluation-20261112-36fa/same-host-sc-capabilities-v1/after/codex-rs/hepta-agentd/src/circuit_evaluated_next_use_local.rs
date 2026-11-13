//! The same original C receipt owner with a concrete local Selector capability.
//! Only the predecessor transport differs; the original journal, actual current
//! reads, complete opaque cut and before/after predecessor protocol stay intact.

use super::*;

pub(crate) struct OriginalCircuitEvaluatedNextUseLocalSourcesV1<'a> {
    pub(crate) snapshot: &'a LearningIterationSnapshotV1,
    pub(crate) selection: &'a OriginalCircuitEvaluatedSelectionReceiptV1,
    pub(crate) live: &'a OriginalCircuitLearningReadClientV1,
    pub(crate) shared: &'a crate::OriginalCircuitPublishedEvidenceReadbackV1,
    pub(crate) selector: &'a crate::OriginalCircuitSelectionLocalReadbackV1,
}

impl NextUseSources for OriginalCircuitEvaluatedNextUseLocalSourcesV1<'_> {
    fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        self.snapshot
    }

    fn trainer(&self) -> Option<&LearningIterationEvidenceClientV1> {
        None
    }

    fn selector(&self) -> OriginalSelectorRead<'_> {
        OriginalSelectorRead::Local(self.selector)
    }

    fn evaluated_owners(
        &self,
    ) -> Option<(
        &crate::OriginalCellQ24TrainingCommandClientV1,
        &crate::OriginalCellEvaluationCommandClientV1,
    )> {
        Some(crate::OriginalCircuitPublishedEvidenceReadbackV1::original_clients(self.shared))
    }

    fn location(&self) -> ObservationLocation {
        ObservationLocation::EvaluatedOwner
    }

    fn require_profile(&self, profile: &Profile) -> Result<(), Error> {
        let Profile::Evaluated(original) = profile else {
            return Err(OwnerError::Binding("original local evaluated NextUse profile").into());
        };
        if self.selection.snapshot() != original.snapshot()
            || self.selection.receipt() != original.receipt()
            || self.selection.attestation() != original.attestation()
            || self.selection.original_receipt_binding() != original.original_receipt_binding()
        {
            return Err(OwnerError::Binding("same original local evaluated Selection").into());
        }
        OriginalCircuitLearningReadClientV1::require_original_local_evaluated_next_use(
            self.live,
            original,
        )?;
        crate::OriginalCircuitPublishedEvidenceReadbackV1::require_original_context(
            self.shared,
            original.original_context(),
        )?;
        crate::OriginalCircuitSelectionLocalReadbackV1::require_original_selection(
            self.selector,
            original,
        ).map_err(|error| Error::LocalSelection(Box::new(error)))?;
        crate::OriginalCircuitSelectionLocalReadbackV1::require_original_shared_predecessors(
            self.selector,
            self.shared,
        ).map_err(|error| Error::LocalSelection(Box::new(error)))?;
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
    pub(crate) async fn attest_original_evaluated_local_completion(
        &mut self,
        source: OriginalCircuitEvaluatedNextUseLocalSourcesV1<'_>,
    ) -> Result<OriginalCircuitEvaluatedNextUseReceiptV1, Error> {
        let completed = match self.command_origin {
            CommandOrigin::FreshCreate => self.attest_source(source).await?,
            CommandOrigin::Recovered => self.readback_source(source).await?,
        };
        self.completed_evaluated_next_use(completed)
    }

    pub(crate) async fn readback_evaluated_local_completion(
        &mut self,
        source: OriginalCircuitEvaluatedNextUseLocalSourcesV1<'_>,
    ) -> Result<OriginalCircuitEvaluatedNextUseReceiptV1, Error> {
        let completed = self.readback_source(source).await?;
        self.completed_evaluated_next_use(completed)
    }

    pub fn into_evaluated_local_shared_command_owner(
        self,
        live: OriginalCircuitLearningReadClientV1,
        shared: crate::OriginalCircuitPublishedEvidenceReadbackV1,
        selector: crate::OriginalCircuitSelectionLocalReadbackV1,
    ) -> Result<
        crate::OriginalCircuitNextUseCommandOwnerV1<W>,
        crate::OriginalCircuitNextUseCommandErrorV1,
    >
    where
        W: Send + 'static,
    {
        crate::OriginalCircuitNextUseCommandOwnerV1::from_original_evaluated_local_shared_receipt_owner(
            self, live, shared, selector,
        )
    }
}

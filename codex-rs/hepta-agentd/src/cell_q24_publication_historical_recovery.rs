//! Recover an already published CURRENT operation using the same Root's
//! acknowledged historical A. This does not reopen A's Source/Cell writers,
//! publish CURRENT again, or recover C's own execution under a new identity.

use super::*;

impl OriginalCellQ24RootPublicationDriverV1 {
    /// Read the actual already published intent from this same Root connection.
    /// The digest is data for the existing recovery operation, not a new grant.
    pub(crate) async fn read_original_recovery_intent(
        &self,
        original_a: &crate::root_historical_task_read_client::OriginalHistoricalTaskReadReceiptV1,
    ) -> Result<Digest32, Error> {
        let original: &OriginalDecision = &self.driver.original;
        OriginalDecision::require_current(original).await?;
        original.decision.require_root_publication()?;
        NeuronGenerationCurrentOwnerV1::require_original_root_selection(
            &self.driver.current,
            &original.decision.snapshot,
            &original.decision.operation,
            self.selected.observation().digest(),
        )?;
        let digest = NeuronGenerationCurrentOwnerV1::read_original_root_recovery_intent(
            &self.driver.current,
            original_a,
        )?;
        OriginalDecision::require_current(original).await?;
        NeuronGenerationCurrentOwnerV1::require_original_root_historical_receipt(
            &self.driver.current,
            original_a,
        )?;
        Ok(digest)
    }

    pub(crate) async fn recover_feature_from_historical_a(
        self,
        recovery: OriginalCellQ24HistoricalFeatureRecoveryV1,
    ) -> Result<PublishedCircuitFeatureTaskV1, Error> {
        let original: &OriginalDecision = &self.driver.original;
        original.require_current().await?;
        original.decision.require_root_publication()?;
        validation::feature_target(
            &original.decision,
            &recovery.target,
            &recovery.definition,
            &recovery.source,
            &recovery.model,
        )?;
        let initial = recovery.original_a.initial_snapshot();
        if initial.request != original.decision.snapshot.request
            || initial.owners != original.decision.snapshot.owners
        {
            return Err(Error::Binding(
                "historical A belongs to another learning iteration",
            ));
        }
        let owners: Arc<OriginalCellQ24LearningStageOwnersV1> = Arc::clone(&original.owners);
        let snapshot = original.decision.snapshot.clone();
        let manifest = original.manifest.clone();
        let bundle = original.decision.bundle.clone();
        let current = Arc::clone(&self.driver.current);
        let original_a = Arc::clone(&recovery.original_a);
        let previous_manifest = recovery.previous_manifest.clone();
        let task = owners
            .with_original_publication(snapshot, manifest, move || {
                let OriginalCellQ24HistoricalFeatureRecoveryV1 {
                    target,
                    definition,
                    source,
                    model: _,
                    previous_manifest,
                    original_a,
                    intent_digest,
                } = recovery;
                NeuronGenerationCurrentOwnerV1::require_original_root_historical_receipt(
                    &self.driver.current,
                    &original_a,
                )?;
                let previous =
                    PublishedCircuitFeatureCompletionV1::read_original_historical_completion(
                        &original_a,
                        previous_manifest,
                    )?;
                let mut selected = self.selected;
                revalidate(&self.driver, &mut selected)?;
                // This existing path accepts Published only. It rechecks the
                // original signed grant/witness and target journal without a
                // new claim, dispatch, genesis or publication CAS.
                let ready = crate::recover_agentd_generation_update_v1(
                    self.driver.current,
                    self.driver.authorities,
                    selected,
                    target,
                    AgentdGenerationUpdateRecoveryV1 {
                        operation_id: self.driver.original.decision.operation.to_string(),
                        intent_digest,
                    },
                )?;
                ready
                    .into_circuit_feature_task(definition, source, previous)
                    .map_err(Error::from)
            })
            .await?;
        // The owner lane has completed all of its postchecks. Reobserve A and
        // CURRENT before releasing the task; equal old receipt bytes alone do
        // not survive expiry or replacement of either original connection.
        NeuronGenerationCurrentOwnerV1::require_original_root_historical_receipt(
            &current,
            &original_a,
        )?;
        PublishedCircuitFeatureCompletionV1::read_original_historical_completion(
            &original_a,
            previous_manifest,
        )?;
        task.require_bundle(&bundle)?;
        NeuronGenerationCurrentOwnerV1::require_original_root_historical_receipt(
            &current,
            &original_a,
        )?;
        Ok(task)
    }
}

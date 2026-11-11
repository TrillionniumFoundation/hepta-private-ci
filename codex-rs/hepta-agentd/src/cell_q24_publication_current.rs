//! Actual CURRENT preparation, exact FinalUse and original cold recovery.
//! Every effect stays inside the original learning owner lane.

use super::*;

impl OriginalCellQ24PublicationDriverV1 {
    /// Open only a real published CURRENT operation. Missing/Pending cannot
    /// trigger preparation, publication, re-signing or a new FinalUse nonce.
    pub async fn recover_feature(
        self,
        selection: OriginalCellQ24SelectionInputsV1,
        recovery: OriginalCellQ24FeatureRecoveryV1,
    ) -> Result<PublishedCircuitFeatureTaskV1, Error> {
        let original: &OriginalDecision = &self.original;
        original.require_current().await?;
        validation::feature_target(
            &self.original.decision,
            &recovery.target,
            &recovery.definition,
            &recovery.source,
            &recovery.model,
        )?;
        let owners: Arc<OriginalCellQ24LearningStageOwnersV1> = Arc::clone(&self.original.owners);
        let snapshot = self.original.decision.snapshot.clone();
        let manifest = self.original.manifest.clone();
        owners
            .with_original_publication(snapshot, manifest, move || {
                let selected = self.load_selection(selection, /*publication*/ None)?;
                recover_selected(self, selected, recovery)
            })
            .await
    }
}

impl OriginalCellQ24SelectionDriverV1 {
    pub async fn prepare_feature(
        self,
        selection: OriginalCellQ24SelectionInputsV1,
        predecessor: AgentdGenerationUpdatePredecessorFilesV1<FileAnchorWitnessStore>,
        target: OriginalCellQ24FeatureTargetV1,
    ) -> Result<OriginalCellQ24PreparedPublicationV1, Error> {
        let original: &OriginalDecision = &self.driver.original;
        original.require_current().await?;
        self.driver.original.decision.require_new_work()?;
        validation::feature_target(
            &self.driver.original.decision,
            &target.target,
            &target.definition,
            &target.source,
            &target.model,
        )?;
        validation::predecessor(
            &self.driver.original.decision,
            &predecessor,
            &target.previous,
            &target.source,
        )?;
        let owners: Arc<OriginalCellQ24LearningStageOwnersV1> =
            Arc::clone(&self.driver.original.owners);
        let snapshot = self.driver.original.decision.snapshot.clone();
        let manifest = self.driver.original.manifest.clone();
        owners
            .with_original_publication(snapshot, manifest, move || {
                self.driver.original.decision.require_new_work()?;
                let selected = self
                    .driver
                    .load_selection(selection, self.publication.as_ref())?;
                prepare_selected(self.driver, selected, predecessor, target)
            })
            .await
    }
}

impl OriginalCellQ24PreparedPublicationV1 {
    pub fn final_use_binding(&self) -> &FinalUseBinding {
        self.prepared.final_use_binding()
    }
    pub fn intent_digest(&self) -> Digest32 {
        self.prepared.intent_digest()
    }

    /// Execute the existing exact FinalUse claim and CURRENT CAS. Returning a
    /// published Feature task does not imply C has run or acknowledged output.
    pub async fn publish(
        self,
        signed: SignedFinalUseGrant,
    ) -> Result<PublishedCircuitFeatureTaskV1, Error> {
        let original: &OriginalDecision = &self.original;
        original.require_current().await?;
        self.original.decision.require_new_work()?;
        if &signed.grant.binding != self.prepared.final_use_binding() {
            return Err(Error::Binding("exact original FinalUse operation"));
        }
        let owners: Arc<OriginalCellQ24LearningStageOwnersV1> = Arc::clone(&self.original.owners);
        let snapshot = self.original.decision.snapshot.clone();
        let manifest = self.original.manifest.clone();
        owners
            .with_original_publication(snapshot, manifest, move || {
                self.original.decision.require_new_work()?;
                validation::require_executable_feature(
                    &self.original.decision.bundle,
                    &self.target_manifest,
                    &self.model,
                    &self.definition,
                    &self.source,
                )?;
                let ready = self.prepared.publish(&signed)?;
                let task =
                    ready.into_circuit_feature_task(self.definition, self.source, self.previous)?;
                Ok(task)
            })
            .await
    }
}

// Both product paths call these only inside the original aggregate lane.
pub(super) fn prepare_selected(
    driver: OriginalCellQ24PublicationDriverV1,
    selected: AgentdSelectedGenerationV1,
    predecessor: AgentdGenerationUpdatePredecessorFilesV1<FileAnchorWitnessStore>,
    target: OriginalCellQ24FeatureTargetV1,
) -> Result<OriginalCellQ24PreparedPublicationV1, Error> {
    if let Some(manifest) = &driver.original.manifest
        && selected.manifest() != manifest
    {
        return Err(Error::Binding("selection differs from original B manifest"));
    }
    let target_manifest = target.target.config.manifest.clone();
    let request = AgentdGenerationUpdateRequestV1 {
        operation_id: driver.original.decision.operation.to_string(),
    };
    let prepared = if driver.original.decision.adopts() {
        crate::prepare_agentd_generation_cold_drained_update_v1(
            driver.current,
            driver.authorities,
            predecessor,
            selected,
            target.target,
            request,
        )?
    } else {
        crate::prepare_agentd_generation_cold_same_model_task_v1(
            driver.current,
            driver.authorities,
            predecessor,
            selected,
            target.target,
            request,
        )?
    };
    Ok::<_, Error>(OriginalCellQ24PreparedPublicationV1 {
        original: driver.original,
        prepared,
        definition: target.definition,
        source: target.source,
        model: target.model,
        target_manifest,
        previous: target.previous,
    })
}

pub(super) fn recover_selected(
    driver: OriginalCellQ24PublicationDriverV1,
    selected: AgentdSelectedGenerationV1,
    recovery: OriginalCellQ24FeatureRecoveryV1,
) -> Result<PublishedCircuitFeatureTaskV1, Error> {
    if let Some(manifest) = &driver.original.manifest
        && selected.manifest() != manifest
    {
        return Err(Error::Binding("recovery differs from original B manifest"));
    }
    let ready = crate::recover_agentd_generation_update_v1(
        driver.current,
        driver.authorities,
        selected,
        recovery.target,
        AgentdGenerationUpdateRecoveryV1 {
            operation_id: driver.original.decision.operation.to_string(),
            intent_digest: recovery.intent_digest,
        },
    )?;
    let task = ready.recover_circuit_feature_task(
        recovery.definition,
        recovery.source,
        recovery.predecessor,
        recovery.original_source.as_ref(),
        &recovery.original_identity,
    )?;
    Ok(task)
}

//! The successor worker supplies the actual AgentdState. New CURRENT/FinalUse
//! effects require its original Running admission immediately inside the owner
//! lane. Existing public publication methods retain their existing contract.

use super::*;
use crate::AgentdState;

pub(crate) fn require_successor_admission(
    state: &AgentdState,
    identity: &AgentdIdentity,
) -> Result<(), Error> {
    if state.identity() != identity
        || !state.automation_admission_ready()?
        || !state.plasticity_admission_ready()?
    {
        return Err(Error::Binding(
            "successor requires its current Running admission",
        ));
    }
    Ok(())
}

impl OriginalCellQ24RootPublicationDriverV1 {
    pub(super) async fn prepare_successor_current(
        self,
        predecessor: AgentdGenerationUpdatePredecessorFilesV1<FileAnchorWitnessStore>,
        target: OriginalCellQ24FeatureTargetV1,
        state: Arc<AgentdState>,
        identity: AgentdIdentity,
        slot: Arc<crate::circuit_q24_successor::SuccessorSlot>,
    ) -> Result<OriginalCellQ24PreparedPublicationV1, Error> {
        let original: &OriginalDecision = &self.driver.original;
        original.decision.require_new_work()?;
        validation::feature_target(
            &original.decision,
            &target.target,
            &target.definition,
            &target.source,
            &target.model,
        )?;
        validation::predecessor(
            &original.decision,
            &predecessor,
            &target.previous,
            &target.source,
        )?;
        require_successor_admission(&state, &identity)?;
        let owners: Arc<OriginalCellQ24LearningStageOwnersV1> = Arc::clone(&original.owners);
        let snapshot = original.decision.snapshot.clone();
        let manifest = original.manifest.clone();
        owners
            .with_original_publication(snapshot, manifest, move || {
                self.driver.original.decision.require_new_work()?;
                let mut selected = self.selected;
                revalidate(&self.driver, &mut selected)?;
                require_successor_admission(&state, &identity)?;
                slot.require_installation_open()
                    .map_err(|_| Error::Binding("successor installation was cancelled"))?;
                let prepared =
                    current::prepare_selected(self.driver, selected, predecessor, target)
                        .map_err(crate::circuit_q24_successor::prepared_uncertain)?;
                require_successor_admission(&state, &identity)
                    .map_err(crate::circuit_q24_successor::prepared_uncertain)?;
                slot.require_installation_open().map_err(|_| {
                    crate::circuit_q24_successor::prepared_uncertain(Error::CommitUncertain)
                })?;
                Ok(prepared)
            })
            .await
            .map_err(crate::circuit_q24_successor::prepared_uncertain)
    }
}

impl OriginalCellQ24PreparedPublicationV1 {
    pub(crate) async fn publish_successor_current(
        self,
        signed: SignedFinalUseGrant,
        state: Arc<AgentdState>,
        identity: AgentdIdentity,
        slot: Arc<crate::circuit_q24_successor::SuccessorSlot>,
    ) -> Result<PublishedCircuitFeatureTaskV1, Error> {
        let original: &OriginalDecision = &self.original;
        original.decision.require_new_work()?;
        if &signed.grant.binding != self.prepared.final_use_binding() {
            return Err(Error::Binding(
                "exact original successor FinalUse operation",
            ));
        }
        require_successor_admission(&state, &identity)?;
        let owners: Arc<OriginalCellQ24LearningStageOwnersV1> = Arc::clone(&original.owners);
        let snapshot = original.decision.snapshot.clone();
        let manifest = original.manifest.clone();
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
                require_successor_admission(&state, &identity)?;
                let prepared: PreparedAgentdGenerationUpdateV1<
                    FileAnchorWitnessStore,
                    FileAnchorWitnessStore,
                > = self.prepared;
                slot.require_installation_open()
                    .map_err(|_| Error::Binding("successor installation was cancelled"))?;
                let ready = prepared.publish(&signed)?;
                let task =
                    ready.into_circuit_feature_task(self.definition, self.source, self.previous)?;
                require_successor_admission(&state, &identity)?;
                slot.require_installation_open()
                    .map_err(|_| Error::CommitUncertain)?;
                Ok(task)
            })
            .await
    }
}

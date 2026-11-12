//! Original selected Artifact to the distinct post-A CURRENT purpose.
//! The ticket is created only by the actual joined scoped receiver.

use super::*;
use crate::root_production_learning_inputs::same_actor_phase::OriginalScopedPublicationTicket;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;

impl OriginalCellQ24ArtifactPublicationDriverV1 {
    /// The original Artifact mutex may wait after the Stage owner was entered.
    /// Check the same concrete Work/Gate at the first Artifact effect, while
    /// retaining the original owner, request validation and transaction.
    pub(crate) fn publish_original_same_actor_candidate(
        self,
        mut request: LearningArtifactPublishRequestV1,
        work: Arc<crate::same_actor_q24_phase_learning::OriginalSameActorLearningWork>,
    ) -> impl std::future::Future<Output = Result<OriginalCellQ24PublishedArtifactForRootV1, Error>>
    {
        let gate = Arc::clone(work.gate());
        let mut closing = CloseSameActorPhaseOnDrop::new(&gate);
        async move {
            self.original
                .owners
                .require_original_same_actor_work(&work)?;
            gate.require_open()
                .map_err(|error| Error::Owner(AgentdError::Io(error)))?;
            let original: &OriginalDecision = &self.original;
            OriginalDecision::require_current(original).await?;
            original.decision.require_new_work()?;
            validation::artifact_request(
                &original.decision,
                original
                    .manifest
                    .as_ref()
                    .ok_or(Error::Binding("original B manifest missing"))?,
                &request,
            )?;
            let owners: Arc<OriginalCellQ24LearningStageOwnersV1> = Arc::clone(&original.owners);
            let snapshot = original.decision.snapshot.clone();
            let manifest = original.manifest.clone();
            let effect_gate = Arc::clone(&gate);
            let result = owners
                .with_original_publication(snapshot, manifest, move || {
                    self.original.decision.require_new_work()?;
                    request.now = self.authorities.now()?;
                    let receipt = {
                        let mut locked = self
                            .authorities
                            .artifacts
                            .lock()
                            .map_err(|_| Error::CommitUncertain)?;
                        let artifacts: &mut LearningArtifactOwnerService = &mut locked;
                        // A gate closed while this real owner lock was pending
                        // prevents a new transaction; an entered transaction still
                        // completes through the original durable owner.
                        effect_gate
                            .require_open()
                            .map_err(|error| Error::Owner(AgentdError::Io(error)))?;
                        artifacts.publish(request)?
                    };
                    Ok(OriginalCellQ24PublishedArtifactForRootV1 {
                        original: self.original,
                        authorities: self.authorities,
                        publication: receipt,
                    })
                })
                .await?;
            // A committed original transaction remains durable. Losing the
            // phase after it is uncertainty, never a safe publication retry.
            gate.require_open().map_err(|_| Error::CommitUncertain)?;
            closing.disarm();
            Ok(result)
        }
    }
}

impl OriginalCellQ24SelectedArtifactForRootV1 {
    pub(crate) fn connect_original_same_actor_current(
        self,
        ticket: OriginalScopedPublicationTicket,
        timeout: Duration,
    ) -> impl std::future::Future<Output = Result<OriginalCellQ24RootPublicationDriverV1, Error>>
    {
        let gate = Arc::clone(ticket.gate());
        // The guard is owned before the future's first poll, including when
        // no task is ever scheduled to drive this connection.
        let mut closing = CloseSameActorPhaseOnDrop::new(&gate);
        async move {
            gate.require_open()
                .map_err(|error| Error::Owner(AgentdError::Io(error)))?;
            OriginalDecision::require_current(&self.original).await?;
            let current: Arc<NeuronGenerationCurrentOwnerV1> =
                ticket.connect_original_current(timeout).await?;
            current.require_original_root_selection(
                &self.original.decision.snapshot,
                &self.original.decision.operation,
                self.selected.observation().digest(),
            )?;
            OriginalDecision::require_current(&self.original).await?;
            gate.require_open()
                .map_err(|error| Error::Owner(AgentdError::Io(error)))?;
            let result = OriginalCellQ24RootPublicationDriverV1 {
                driver: OriginalCellQ24PublicationDriverV1 {
                    original: self.original,
                    current,
                    authorities: self.authorities,
                },
                selected: self.selected,
            };
            closing.disarm();
            Ok(result)
        }
    }
}

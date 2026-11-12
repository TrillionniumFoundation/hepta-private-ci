//! The positive remote source is private to the consuming original C command
//! host. It cannot issue a grant, run a task, supply an observation or reopen a
//! signer. Every observation reads the actual published Cell and TaskSource.

use super::*;

pub(crate) struct OriginalCircuitCandidateNextUseRemoteSourcesV1<'a> {
    pub snapshot: &'a LearningIterationSnapshotV1,
    pub live: &'a crate::OriginalCircuitCandidateLearningReadClientV1,
    pub trainer: &'a LearningIterationEvidenceClientV1,
    pub selector: &'a LearningIterationEvidenceClientV1,
}

impl NextUseSources for OriginalCircuitCandidateNextUseRemoteSourcesV1<'_> {
    fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        self.snapshot
    }
    fn trainer(&self) -> &LearningIterationEvidenceClientV1 {
        self.trainer
    }
    fn selector(&self) -> &LearningIterationEvidenceClientV1 {
        self.selector
    }
    fn location(&self) -> ObservationLocation {
        ObservationLocation::RemoteOwner
    }
    async fn observe(
        &self,
        config: &OriginalCircuitNextUseReceiptConfigV1,
    ) -> Result<LearningIterationObservationV1, Error> {
        let context = self.live.original_context();
        if context.prefix() != &config.selection
            || context.scope() != &config.scope
            || context.verifier().trust_digest() != config.verifier.trust_digest()
            || context.verifier().scope_digest() != config.verifier.scope_digest()
            || context.verifier().objective_digest() != config.verifier.objective_digest()
            || context.training_attestation() != &config.training_evidence
            || context.selection_attestation() != Some(&config.selection_evidence)
        {
            return Err(OwnerError::Binding("same original positive C source").into());
        }
        let started = now()?;
        let binding = context.binding(started)?;
        authenticate_candidate_observer(config, context, started)?;
        let actual = crate::OriginalCircuitCandidateLearningReadClientV1::read_current(self.live).await?;
        let current = now()?;
        if current < started || context.binding(current)? != binding {
            return Err(OwnerError::Binding("full positive C source window after actual I/O").into());
        }
        authenticate_candidate_observer(config, context, current)?;
        Ok(actual.observation().clone())
    }
}

fn authenticate_candidate_observer(
    config: &OriginalCircuitNextUseReceiptConfigV1,
    context: &crate::OriginalCircuitCandidateLearningReadContextV1,
    current: u64,
) -> Result<(), Error> {
    config.verifier.require_signer_binding(
        LearningEvidenceRoleV1::Observer,
        &config.signer,
        current,
    )?;
    for original in context.authenticate(current)? {
        verify_independent_roles(original.principal(), &config.signer.principal, current)
            .map_err(SignedEvidenceError::from)?;
        if original.controller_id() == &config.signer.controller_id {
            return Err(SignedEvidenceError::ControllerCollision.into());
        }
    }
    Ok(())
}

impl<W: AnchorWitnessStore> OriginalCircuitNextUseReceiptOwnerV1<W> {
    /// Consume the same original enrolled Observer and its witnessed journal.
    /// Its private creation/recovery brand remains the command admission rule.
    pub fn into_candidate_command_owner(
        self,
        live: crate::OriginalCircuitCandidateLearningReadClientV1,
        trainer: LearningIterationEvidenceClientV1,
        selector: LearningIterationEvidenceClientV1,
    ) -> Result<
        crate::OriginalCircuitCandidateNextUseCommandOwnerV1<W>,
        crate::OriginalCircuitCandidateNextUseCommandErrorV1,
    >
    where
        W: Send + 'static,
    {
        crate::OriginalCircuitCandidateNextUseCommandOwnerV1::from_original_receipt_owner(
            self, live, trainer, selector,
        )
    }

    pub(crate) async fn attest_original_candidate_remote_completion(
        &mut self,
        source: OriginalCircuitCandidateNextUseRemoteSourcesV1<'_>,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        self.attest_source(source).await
    }

    pub(crate) async fn readback_candidate_remote(
        &mut self,
        source: OriginalCircuitCandidateNextUseRemoteSourcesV1<'_>,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        self.readback_source(source).await
    }
}

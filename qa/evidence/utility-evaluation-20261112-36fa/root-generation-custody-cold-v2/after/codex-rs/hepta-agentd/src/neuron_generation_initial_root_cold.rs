//! Explicit cold entry for one existing original initial publication.
//!
//! The trusted Root host supplies its actually reopened concrete CURRENT,
//! authorities, selected material and original journal files. Protected history
//! alone never constructs Ready; the unchanged original recovery performs the
//! complete publication, Artifact, FinalUse, journal and live-current checks.

use super::*;

impl<W: AnchorWitnessStore> OriginalRootInitialGenerationCustodyV1<W> {
    /// Recover custody after the old coordinator value has been lost. This
    /// consumes no new grant and does not prepare, initialize or publish. It
    /// accepts only the original operation and existing target, delegates to
    /// `recover_agentd_generation_initial_v1`, then rechecks the same protected
    /// readback before retaining the original Ready value.
    ///
    /// This recovers generation custody, not Source/Cell deployment. A later
    /// task installation must explicitly choose the original Source lifecycle;
    /// recovery never falls back to Create after an uncertain installation.
    pub fn recover_from_original_current(
        current: Arc<NeuronGenerationCurrentOwnerV1>,
        authorities: AgentdGenerationUpdateAuthoritiesV1,
        selected: AgentdSelectedGenerationV1,
        target: AgentdGenerationUpdateTargetV1<W>,
        recovery: AgentdGenerationUpdateRecoveryV1,
    ) -> Result<Self, AgentdError> {
        require_root()?;
        let original = current.recover_initial_operation(
            &recovery.operation_id,
            recovery.intent_digest,
        )?;
        let binding = original.final_use_binding().clone();
        let before = current.read_initial_operation(&original)?;
        let ready = recover_agentd_generation_initial_v1(
            Arc::clone(&current),
            authorities.clone(),
            selected,
            target,
            AgentdGenerationUpdateRecoveryV1 {
                operation_id: recovery.operation_id.clone(),
                intent_digest: recovery.intent_digest,
            },
        )?;
        let operation = OriginalInitialOperation {
            current,
            authorities,
            recovery,
            binding,
        };
        if operation.read_original()? != before {
            return Err(invalid("original initial publication changed across cold recovery"));
        }
        Ok(Self {
            operation,
            phase: InitialPhase::Ready(Box::new(ready)),
        })
    }
}

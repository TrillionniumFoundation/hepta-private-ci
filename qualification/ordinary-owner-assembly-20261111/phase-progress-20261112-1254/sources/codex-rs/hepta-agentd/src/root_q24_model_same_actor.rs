//! One actual phase receiver supplies the original transport and its retained
//! same-stream shutdown guard. It does not expose a factory from public pins.

use super::*;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;

impl AgentdRootQ24ModelFactoryV1 {
    /// The private receiver retains the required guard from the very socket
    /// used for from_stream_until at gate.deadline().instant(), then transfers
    /// both here. Only the original successful Observe completes construction.
    pub(crate) async fn from_original_same_actor_handoff(
        transport: RootObservationStream,
        profile: HostAuthorityQ24ModelFactoryProfileV1,
        initial: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        spawn_generation: u64,
        files: (File, File),
        phase: RequiredSameActorPhaseChannel,
    ) -> Result<Self, AgentdError> {
        let mut closing = phase.failure_scope();
        phase.require_open().map_err(refused)?;
        let (journal, witness) = files;
        profile.require_files(&journal, &witness)?;
        let mut factory = Self {
            transport: Some(transport),
            next_request_id: 1,
            profile,
            initial,
            scope,
            generation: Generation::new(spawn_generation).map_err(refused)?,
            files: Some((journal, witness)),
            owner: None,
            fenced: false,
            phase: Some(phase),
        };
        factory.exchange(Command::Observe).await?;
        factory.require_original_phase()?;
        closing.disarm();
        Ok(factory)
    }

    pub(super) fn original_phase_failure_scope(&self) -> Option<CloseSameActorPhaseOnDrop> {
        self.phase
            .as_ref()
            .map(|phase: &RequiredSameActorPhaseChannel| phase.failure_scope())
    }

    pub(super) fn require_original_phase(&self) -> Result<(), AgentdError> {
        if let Some(phase) = &self.phase {
            let phase: &RequiredSameActorPhaseChannel = phase;
            phase.require_open().map_err(refused)?;
        }
        Ok(())
    }
}

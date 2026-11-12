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

    /// Close only this actual required Model purpose after the real worker
    /// and local owner lanes have joined. Keep the factory, files, stream and
    /// failure guard held; this is not a new Observe or a Model operation.
    pub(crate) fn retire_original_model_after_root_intent(
        &mut self,
        intent: &crate::same_actor_q24_deployment::OriginalRootRetirementIntent,
        identity: &crate::AgentdIdentity,
        gate: &std::sync::Arc<crate::same_actor_q24_phase_gate::SameActorPhaseGate>,
    ) -> Result<(), AgentdError> {
        let mut closing = CloseSameActorPhaseOnDrop::new(gate);
        intent.require_original_origin(identity, gate)?;
        let phase = self.phase.as_ref()
            .ok_or_else(|| refused("Model retirement has no original phase channel"))?;
        if !std::sync::Arc::ptr_eq(phase.gate(), gate) || self.fenced {
            return Err(refused("Model retirement is foreign or already fenced"));
        }
        phase.require_open().map_err(refused)?;
        let transport = self.transport.as_ref()
            .ok_or_else(|| refused("Model retirement has an uncertain exchange"))?;
        let root = RootObservationStream::root_lifetime(transport);
        crate::root_observation_stream::check_lifetime(root.get_ref()).map_err(refused)?;
        // Exclusive &mut self and the populated transport slot exclude any
        // in-flight factory exchange. Fence before changing the real socket.
        self.fenced = true;
        phase.shutdown_original_after_root_intent(intent)?;
        crate::root_observation_stream::check_lifetime(root.get_ref()).map_err(refused)?;
        intent.require_original_origin(identity, gate)?;
        closing.disarm();
        Ok(())
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

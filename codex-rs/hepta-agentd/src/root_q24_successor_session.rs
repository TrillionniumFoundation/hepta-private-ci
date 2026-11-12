//! Read-only proof of the same original five-lane session. This does not
//! duplicate its one-use publication connection or acquire any authority.

use super::*;

pub(crate) struct OriginalQ24SuccessorSession {
    original: HostAuthorityPublicBootstrapV1,
    identity: AgentdIdentity,
    authority: ProductionAuthorityLease,
    verifier: Arc<dyn ProductionAuthorityVerifier>,
    phase: Option<Arc<crate::same_actor_q24_phase_gate::SameActorPhaseGate>>,
}

impl OriginalQ24SuccessorSession {
    pub(crate) fn capture_original_successor_session(
        session: &AgentdRootAuthoritySession,
        original: &HostAuthorityPublicBootstrapV1,
        identity: &AgentdIdentity,
    ) -> Result<Self, AgentdError> {
        if original.registered_identity.identity()? != *identity
            || session.authority().grant_digest != original.writer_proof.sha256()?
        {
            return Err(refused("successor differs from the original Root writer"));
        }
        let observed = Self {
            original: original.clone(),
            identity: identity.clone(),
            authority: session.authority(),
            verifier: session.verifier(),
            phase: None,
        };
        observed.require_current_successor_session()?;
        Ok(observed)
    }

    pub(crate) fn capture_original_same_actor_successor_session(
        session: &AgentdRootAuthoritySession,
        original: &HostAuthorityPublicBootstrapV1,
        identity: &AgentdIdentity,
        phase: &Arc<crate::same_actor_q24_phase_gate::SameActorPhaseGate>,
    ) -> Result<Self, AgentdError> {
        let mut closing = crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop::new(phase);
        session.require_original_same_actor_phase_origin(phase)
            .map_err(|error| refused(&error.to_string()))?;
        let mut captured = Self::capture_original_successor_session(session, original, identity)?;
        captured.phase = Some(Arc::clone(phase));
        captured.require_original_same_actor_phase(phase)?;
        closing.disarm();
        Ok(captured)
    }

    pub(crate) fn require_original_same_actor_phase(
        &self,
        phase: &Arc<crate::same_actor_q24_phase_gate::SameActorPhaseGate>,
    ) -> Result<(), AgentdError> {
        phase.require_open().map_err(|error| refused(&error.to_string()))?;
        if !self.phase.as_ref().is_some_and(|original| Arc::ptr_eq(original, phase)) {
            return Err(refused("successor belongs to another original same-actor phase"));
        }
        self.require_current_successor_session()?;
        phase.require_open().map_err(|error| refused(&error.to_string()))?;
        Ok(())
    }

    /// A separate scoped purpose is claimed only by the original Joined
    /// receiver's opaque ticket. This cannot duplicate the Initial slot.
    pub(crate) fn take_original_scoped_publication_connection(
        &self,
        ticket: &crate::root_production_learning_inputs::same_actor_phase::OriginalScopedPublicationTicket,
    ) -> Result<RootGenerationPublicationConnectionV1, AgentdError> {
        ticket.claim_original_session(self)?;
        self.require_original_same_actor_phase(ticket.gate())?;
        let connection = RootGenerationPublicationConnectionV1 {
            original: self.original.clone(),
            identity: self.identity.clone(),
            authority: self.authority.clone(),
            verifier: Arc::clone(&self.verifier),
        };
        connection.require_same_successor_session(self)?;
        self.require_original_same_actor_phase(ticket.gate())?;
        Ok(connection)
    }

    pub(crate) fn identity(&self) -> &AgentdIdentity {
        &self.identity
    }

    pub(crate) fn writer_proof(&self) -> Result<String, AgentdError> {
        Ok(self.original.writer_proof.sha256()?.as_str().to_owned())
    }

    pub(crate) fn require_current_successor_session(&self) -> Result<(), AgentdError> {
        // SAFETY: only reads the current process's kernel credentials.
        let (uid, effective_uid) = unsafe { (libc::getuid(), libc::geteuid()) };
        if uid == 0
            || effective_uid == 0
            || uid != self.original.consumer.uid
            || effective_uid != self.original.consumer.uid
            || std::process::id() != self.original.consumer.pid
        {
            return Err(refused("successor left the original Root consumer"));
        }
        self.verifier
            .verify_sender_process_binding(
                &self.authority,
                &self.identity.agent_id,
                &self.original.writer.local_lease_id,
                self.original.writer.local_lease_generation,
                self.identity.spawn_generation,
            )
            .map_err(AgentdError::GenerationFenced)
    }
}

impl RootGenerationPublicationConnectionV1 {
    pub(crate) fn require_same_successor_session(
        &self,
        expected: &OriginalQ24SuccessorSession,
    ) -> Result<(), AgentdError> {
        self.require_original_publication_session()?;
        expected.require_current_successor_session()?;
        if !Arc::ptr_eq(&self.verifier, &expected.verifier)
            || self.identity != expected.identity
            || serde_json::to_vec(&self.original)? != serde_json::to_vec(&expected.original)?
            || self.authority.grant_digest != expected.authority.grant_digest
        {
            return Err(refused("successor uses another original Root session"));
        }
        self.require_original_publication_session()?;
        expected.require_current_successor_session()
    }
}

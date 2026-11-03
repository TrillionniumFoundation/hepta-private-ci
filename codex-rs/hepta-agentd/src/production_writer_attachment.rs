//! Bind one recovered production writer to the original Agentd launch without
//! conflating the Fleet lifecycle counter with the writer's lease counter.

use codex_hepta_cognitive_store::ProductionDurableWriter;

use super::AgentdProductionWriterHost;
use crate::AgentdError;
use crate::AgentdIdentity;

/// Private, in-memory association made by the authenticated recovery path.
/// This value neither creates authority nor authorizes an external effect;
/// the original live verifier and Fleet/FinalUse gates remain authoritative.
#[derive(Clone)]
pub(super) struct RecoveredWriterAttachment {
    identity: AgentdIdentity,
    lease_id: String,
    lease_generation: u64,
}

impl RecoveredWriterAttachment {
    pub(super) fn new(identity: &AgentdIdentity, writer: &ProductionDurableWriter) -> Self {
        Self {
            identity: identity.clone(),
            lease_id: writer.lease_id().to_owned(),
            lease_generation: writer.generation(),
        }
    }
}

impl AgentdProductionWriterHost {
    pub(crate) fn require_attachment(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        if self.writer.owner_agent_id() != &identity.agent_id {
            return Err(AgentdError::GenerationFenced(
                "production cognitive writer owner does not match Agentd identity".to_owned(),
            ));
        }
        match &self.attachment {
            Some(attachment)
                if attachment.identity == *identity
                    && attachment.lease_id == self.writer.lease_id()
                    && attachment.lease_generation == self.writer.generation() => Ok(()),
            Some(_) => Err(AgentdError::GenerationFenced(
                "production cognitive writer was recovered for a different Agentd launch or lease"
                    .to_owned(),
            )),
            // The explicitly enabled qualification seam predates exact-cut
            // recovery. Preserve its old constraint; it cannot obtain the
            // production mutation capability or a live verifier this way.
            None if self.writer.generation() == identity.spawn_generation => Ok(()),
            None => Err(AgentdError::GenerationFenced(format!(
                "unbound qualification writer generation {} does not match Agentd spawn generation {}",
                self.writer.generation(), identity.spawn_generation,
            ))),
        }
    }
}

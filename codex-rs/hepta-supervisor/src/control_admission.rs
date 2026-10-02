//! Ordinary controls cannot supersede a stored exact exit. Emergency Kill uses
//! acquired owners rather than serving admission; the daemon checks the live
//! fence and advances its owner-local control revision before dispatch.

use codex_hepta_contracts::AgentId;

use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::runtime::AgentSlot;

pub(crate) fn ensure_main_exit_unobserved<P>(
    agent_id: &AgentId,
    slot: &AgentSlot<P>,
) -> Result<(), SupervisorError> {
    if slot.observed_exit.is_some() {
        return Err(SupervisorError::Invalid(format!(
            "agent {agent_id} has an observed main exit awaiting durable cleanup"
        )));
    }
    Ok(())
}

impl<D: ProcessDriver> Supervisor<D> {
    #[cfg(unix)]
    pub(crate) fn preflight_kill(&self, agent_id: &AgentId) -> Result<(), SupervisorError> {
        self.record(agent_id)?;
        let slot = self
            .slots
            .get(agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
        // Fencing and lifecycle generation drift do not revoke ownership of a
        // retained adopted lifetime. Neither a rejected lease nor a pending
        // idle restart, however, is an owned handle that grants signal authority.
        if slot.runtime.is_none() && slot.matrix.runtime.is_none() {
            return Err(SupervisorError::Invalid(format!(
                "agent {agent_id} is not active"
            )));
        }
        Ok(())
    }
}

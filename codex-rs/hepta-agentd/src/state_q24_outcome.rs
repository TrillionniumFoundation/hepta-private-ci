//! An accepted control future owns the real producer until its work returns.
//! A failed postcheck is uncertainty, even if the original append completed.

use codex_hepta_agent_protocol::Q24OriginalTerminalOutcomeReceiptV1;
use codex_hepta_agent_protocol::Q24OriginalTerminalOutcomeRequestV1;
use codex_hepta_fleet::AgentLifecycle;

use super::*;

impl AgentdState {
    pub(crate) fn attach_original_q24_outcome_control(
        &self,
        producer: Arc<crate::OriginalCellQ24TaskLedgerProducerV1>,
    ) -> Result<(), AgentdError> {
        producer.require_original_control_identity(&self.identity)?;
        if self.circuit_task.get().is_none() || self.circuit_task_invocation.get().is_none() {
            return Err(AgentdError::Invalid(
                "original Q24 task owner is absent".into(),
            ));
        }
        self.original_q24_outcome_control
            .set(producer)
            .map_err(|_| AgentdError::Invalid("original Q24 Outcome owner already attached".into()))
    }

    pub(crate) fn submit_original_q24_control_outcome(
        &self,
        request: &Q24OriginalTerminalOutcomeRequestV1,
    ) -> Result<Q24OriginalTerminalOutcomeReceiptV1, AgentdError> {
        self.require_original_q24_outcome_current()?;
        let producer: &Arc<crate::OriginalCellQ24TaskLedgerProducerV1> =
            self.original_q24_outcome_control.get().ok_or_else(|| {
                AgentdError::Protocol("original Q24 Outcome owner unavailable".into())
            })?;
        producer.require_original_control_identity(&self.identity)?;
        // No detached blocking task can outlive this accepted connection.
        // The original producer retains its signature, deadline and witness.
        let receipt = producer.submit_original_control_outcome(request)?;
        self.require_original_q24_outcome_current()?;
        Ok(receipt)
    }

    fn require_original_q24_outcome_current(&self) -> Result<(), AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        if runtime.current_generation != self.identity.spawn_generation
            || runtime.lifecycle != AgentLifecycle::Running
            || !runtime.app_server_ready
            || !runtime.critical_stores_ready
            || !runtime.revocation_ready
            || !runtime.required_ports_ready
            || !runtime.admission_open
            || runtime.drain_requested
            || runtime.fenced
        {
            return Err(AgentdError::GenerationFenced(
                "original Q24 Outcome admission is no longer current".into(),
            ));
        }
        Ok(())
    }
}

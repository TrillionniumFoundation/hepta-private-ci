//! An observation of completed history remains tied to the new actual Root
//! session. Keeping its DATA in memory never extends that session's lifetime.

use std::sync::Arc;

use codex_hepta_agent_protocol::OriginalQ24CompletedHistoryDataV1;
use codex_hepta_fleet::AgentLifecycle;

use super::AgentdState;
use super::poisoned_state;
use crate::AgentdError;
use crate::root_completed_learning_history::OriginalCompletedLearningHistoryV1;

impl AgentdState {
    pub(crate) fn attach_original_q24_completed_history(
        &self,
        completed: Arc<OriginalCompletedLearningHistoryV1>,
    ) -> Result<(), AgentdError> {
        OriginalCompletedLearningHistoryV1::require_original_current(&completed, &self.identity)?;
        let result = completed
            .data()
            .validate_data()
            .map_err(AgentdError::Protocol);
        OriginalCompletedLearningHistoryV1::require_original_current(&completed, &self.identity)?;
        result?;
        self.original_q24_completed_history
            .set(completed)
            .map_err(|_| AgentdError::Invalid("original completed history already attached".into()))
    }

    pub(crate) fn read_original_q24_completed_history(
        &self,
    ) -> Result<Option<OriginalQ24CompletedHistoryDataV1>, AgentdError> {
        self.require_original_completed_history_current()?;
        let Some(completed) = self.original_q24_completed_history.get() else {
            // Missing is never promoted from process health or an old snapshot.
            self.require_original_completed_history_current()?;
            return Ok(None);
        };
        OriginalCompletedLearningHistoryV1::require_original_current(completed, &self.identity)?;
        let data = completed.data().clone();
        let result = data.validate_data().map_err(AgentdError::Protocol);
        // Both postchecks run even when DATA validation or the Root postcheck
        // fails. No runtime mutex is held across the original Root exchange.
        let root_after =
            OriginalCompletedLearningHistoryV1::require_original_current(completed, &self.identity);
        let generation_after = self.require_original_completed_history_current();
        root_after?;
        generation_after?;
        result?;
        Ok(Some(data))
    }

    fn require_original_completed_history_current(&self) -> Result<(), AgentdError> {
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
                "original completed-history recipient is no longer current".into(),
            ));
        }
        Ok(())
    }
}

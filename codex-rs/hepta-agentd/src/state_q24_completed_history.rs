//! An observation of completed history remains tied to the new actual Root
//! session. Keeping its DATA in memory never extends that session's lifetime.

use std::sync::Arc;

use codex_hepta_agent_protocol::OriginalQ24CompletedHistoryDataV1;
use codex_hepta_agent_protocol::OriginalQ24TerminalAcceptanceDataV1;
use codex_hepta_fleet::AgentLifecycle;

use super::AgentdState;
use super::poisoned_state;
use crate::AgentdError;
use crate::root_completed_learning_history::OriginalCompletedLearningAcknowledgementV1;
use crate::root_completed_learning_history::OriginalCompletedLearningHistoryV1;

impl AgentdState {
    pub(crate) fn attach_original_q24_terminal_acceptance(
        &self,
        acknowledged: OriginalCompletedLearningAcknowledgementV1,
    ) -> Result<(), AgentdError> {
        self.require_original_completed_history_current()?;
        OriginalCompletedLearningAcknowledgementV1::require_original_current(
            &acknowledged,
            &self.identity,
        )?;
        let result = OriginalCompletedLearningAcknowledgementV1::data(&acknowledged)
            .validate_data()
            .map_err(AgentdError::Protocol);
        let root_after = OriginalCompletedLearningAcknowledgementV1::require_original_current(
            &acknowledged,
            &self.identity,
        );
        let generation_after = self.require_original_completed_history_current();
        root_after?;
        generation_after?;
        result?;
        // The caller has completed its own terminal checks. Nothing fallible
        // follows a successful set before it can enter its shutdown wait.
        self.original_q24_terminal_acceptance
            .set(acknowledged)
            .map_err(|_| {
                AgentdError::Invalid("original terminal acceptance already attached".into())
            })
    }

    pub(crate) fn read_original_q24_terminal_acceptance(
        &self,
    ) -> Result<Option<OriginalQ24TerminalAcceptanceDataV1>, AgentdError> {
        self.require_original_completed_history_current()?;
        let Some(acknowledged) = self.original_q24_terminal_acceptance.get() else {
            self.require_original_completed_history_current()?;
            return Ok(None);
        };
        OriginalCompletedLearningAcknowledgementV1::require_original_current(
            acknowledged,
            &self.identity,
        )?;
        let data = OriginalCompletedLearningAcknowledgementV1::data(acknowledged).clone();
        let result = data.validate_data().map_err(AgentdError::Protocol);
        let root_after = OriginalCompletedLearningAcknowledgementV1::require_original_current(
            acknowledged,
            &self.identity,
        );
        let generation_after = self.require_original_completed_history_current();
        root_after?;
        generation_after?;
        result?;
        Ok(Some(data))
    }

    pub(crate) fn attach_original_q24_completed_history(
        &self,
        completed: Arc<OriginalCompletedLearningHistoryV1>,
    ) -> Result<(), AgentdError> {
        OriginalCompletedLearningHistoryV1::require_original_current(&completed, &self.identity)?;
        let result = OriginalCompletedLearningHistoryV1::data(&completed)
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
        let data = OriginalCompletedLearningHistoryV1::data(completed).clone();
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
        // The fixed startup identity precedes the actual Starting -> Running
        // Fleet transition. Overflow cannot denote a current incarnation.
        let running_generation = self.identity.spawn_generation.checked_add(1);
        if Some(runtime.current_generation) != running_generation
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

//! The registered terminal worker lane participates in the original Agentd
//! lifecycle. This is private state; DrainSnapshot wire fields remain unchanged.

use std::sync::Arc;

use codex_hepta_fleet::AgentLifecycle;

use super::AgentdState;
use super::poisoned_state;
use crate::AgentdError;
use crate::terminal_learning::TerminalNativeLifetimeV1;

impl AgentdState {
    pub(crate) fn attach_terminal_native_lifetime(
        &self,
        lifetime: Arc<TerminalNativeLifetimeV1>,
    ) -> Result<(), AgentdError> {
        // Serialize installation with the existing drain/fence state. A late
        // installation cannot miss a close which observed no registered lane.
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        if runtime.drain_requested
            || runtime.fenced
            || runtime.terminal_native_fenced
            || matches!(
                runtime.lifecycle,
                AgentLifecycle::Draining | AgentLifecycle::Stopped | AgentLifecycle::Failed
            )
        {
            lifetime.close();
            return Err(AgentdError::GenerationFenced(
                "terminal native owner cannot attach to a closed runtime".into(),
            ));
        }
        if let Some(current) = self.terminal_native_lifetime.get() {
            if !Arc::ptr_eq(current, &lifetime) {
                return Err(AgentdError::Invalid(
                    "terminal native owner cannot be replaced".into(),
                ));
            }
        } else {
            self.terminal_native_lifetime
                .set(Arc::clone(&lifetime))
                .map_err(|_| {
                    AgentdError::Invalid("terminal native owner already installed".into())
                })?;
        }
        Ok(())
    }

    pub(crate) fn fence_terminal_native_admission(&self) {
        if let Ok(mut runtime) = self.runtime.lock() {
            runtime.terminal_native_fenced = true;
            self.close_terminal_native_admission();
        } else {
            // Poison prevents all later registration and must also close an
            // already installed worker lane.
            self.close_terminal_native_admission();
        }
    }

    pub(crate) fn close_terminal_native_admission(&self) {
        if let Some(lifetime) = self.terminal_native_lifetime.get() {
            lifetime.close();
        }
    }

    pub(crate) fn terminal_native_drain_blockers(&self) -> u32 {
        self.terminal_native_lifetime
            .get()
            .map_or(/*default*/ 0, |lifetime| lifetime.blockers())
    }
}

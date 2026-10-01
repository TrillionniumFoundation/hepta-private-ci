//! Capability-local attachment and drain semantics. A missing handle is not
//! proof of absence; withdrawn routes retain the existing owner for drain reads.
use super::AgentdState;
use super::poisoned_state;
use crate::AgentdError;
use codex_hepta_agent_components::automation::AutomationStore;

#[derive(Clone, Default)]
pub(super) enum AutomationAttachment {
    #[default]
    Unavailable,
    Absent,
    Available(AutomationStore),
    Retained(AutomationStore),
}

impl AutomationAttachment {
    pub(super) fn serving(&self) -> Option<&AutomationStore> {
        match self {
            Self::Available(store) => Some(store),
            Self::Unavailable | Self::Absent | Self::Retained(_) => None,
        }
    }

    pub(super) async fn drain_blockers(&self) -> Result<u32, AgentdError> {
        match self {
            Self::Available(store) | Self::Retained(store) => {
                // Uncertain provider effects survive their waiting caller and
                // process. Query the retained original owner before reporting
                // a zero drain cut, even when no local worker remains.
                let pending =
                    store
                        .pending_authorized_taskflow_effects(1)
                        .await
                        .map_err(|error| {
                            AgentdError::Protocol(format!(
                                "read durable effect drain blockers: {error}"
                            ))
                        })?;
                Ok(store
                    .drain_blockers()
                    .await?
                    .saturating_add(u32::from(!pending.is_empty())))
            }
            Self::Absent => Ok(0),
            Self::Unavailable => Ok(1),
        }
    }
}

impl AgentdState {
    pub(crate) fn attach_automation_store(
        &self,
        store: AutomationStore,
    ) -> Result<(), AgentdError> {
        if store.owner_agent_id() != &self.identity.agent_id {
            return Err(AgentdError::GenerationFenced(
                "automation store owner does not match agentd identity".to_string(),
            ));
        }
        let mut attachment = self.automation.lock().map_err(poisoned_state)?;
        if attachment.serving().is_some() {
            return Err(AgentdError::Protocol(
                "automation store was attached more than once".to_string(),
            ));
        }
        *attachment = AutomationAttachment::Available(store);
        Ok(())
    }

    pub(crate) fn mark_automation_unavailable(&self) -> Result<(), AgentdError> {
        *self.automation.lock().map_err(poisoned_state)? = AutomationAttachment::Unavailable;
        Ok(())
    }

    pub(crate) fn automation_is_available(&self) -> Result<bool, AgentdError> {
        Ok(self
            .automation
            .lock()
            .map_err(poisoned_state)?
            .serving()
            .is_some())
    }

    /// Withdraw only the serving route. The existing owner still answers drain
    /// queries; this grants neither topology retirement nor terminal effects.
    pub(crate) fn retain_automation_for_drain(&self) -> Result<(), AgentdError> {
        let mut attachment = self.automation.lock().map_err(poisoned_state)?;
        let store = match &*attachment {
            AutomationAttachment::Available(store) | AutomationAttachment::Retained(store) => {
                store.clone()
            }
            AutomationAttachment::Unavailable | AutomationAttachment::Absent => {
                return Err(AgentdError::Protocol(
                    "automation drain requires the retained owner".to_string(),
                ));
            }
        };
        *attachment = AutomationAttachment::Retained(store);
        Ok(())
    }

    /// Called only after the selected profile's final revalidation. Recheck the
    /// directory under the existing Agent writer lock before publishing absence.
    pub(crate) fn mark_automation_absent(&self) -> Result<(), AgentdError> {
        self.refresh_generation()?;
        if std::fs::read_dir(self.identity.layout.automation_root())?
            .next()
            .transpose()?
            .is_some()
        {
            return Err(AgentdError::GenerationFenced(
                "unselected Automation acquired owner state before publication".to_string(),
            ));
        }
        let mut attachment = self.automation.lock().map_err(poisoned_state)?;
        if !matches!(
            *attachment,
            AutomationAttachment::Unavailable | AutomationAttachment::Absent
        ) {
            return Err(AgentdError::Protocol(
                "retained automation owner cannot become absent".to_string(),
            ));
        }
        *attachment = AutomationAttachment::Absent;
        Ok(())
    }
}

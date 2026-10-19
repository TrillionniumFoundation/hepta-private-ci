use super::*;
use codex_hepta_automation::AuthorizedEffectIntent;

impl AgentdState {
    pub(crate) fn require_effect_ready(&self) -> Result<(), AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        require_automation_ready(
            runtime.lifecycle,
            runtime.app_server_ready,
            runtime.critical_stores_ready,
            runtime.revocation_ready,
            runtime.required_ports_ready,
            runtime.admission_open,
            runtime.fenced,
        )
    }

    pub(super) async fn resume_automation_effect(
        &self,
        intent: &AuthorizedEffectIntent,
        material: crate::automation_effect_host::AgentdEffectMaterial<'_>,
        signed_grant: &codex_hepta_contracts::SignedFinalUseGrant,
        command_id: &str,
        deadline: std::time::Instant,
    ) -> Result<crate::AutomationEffectReconcileSnapshot, AgentdError> {
        self.require_effect_ready()?;
        let store = self
            .automation
            .lock()
            .map_err(poisoned_state)?
            .clone()
            .ok_or_else(|| AgentdError::Protocol(AUTOMATION_UNAVAILABLE_MESSAGE.to_owned()))?;
        let host = self.automation_effect_host().ok_or_else(|| {
            AgentdError::Protocol(AUTOMATION_EFFECT_UNAVAILABLE_MESSAGE.to_owned())
        })?;
        let result = host
            .resume_effect(
                &store,
                self,
                crate::automation_effect_host::AgentdEffectResumeInput {
                    intent,
                    material,
                    signed_grant,
                    command_id,
                    deadline,
                },
            )
            .await?;
        self.require_effect_ready()?;
        use crate::automation_effect_host::AgentdAutomationEffectReconcileOutcome as Outcome;
        Ok(match result {
            Outcome::Observed { receipt, chain } => crate::AutomationEffectReconcileSnapshot {
                state: crate::AutomationEffectReconcileState::Terminal,
                effect: Some(effect_snapshot(*receipt)?),
                chain: chain.map(|chain| *chain),
            },
            Outcome::Indeterminate => crate::AutomationEffectReconcileSnapshot {
                state: crate::AutomationEffectReconcileState::Indeterminate,
                effect: None,
                chain: None,
            },
            Outcome::ProvenAbsent => crate::AutomationEffectReconcileSnapshot {
                state: crate::AutomationEffectReconcileState::ProvenAbsent,
                effect: None,
                chain: None,
            },
        })
    }

    pub(super) async fn observe_automation_effect(
        &self,
        intent: &AuthorizedEffectIntent,
        command_id: &str,
    ) -> Result<crate::AutomationEffectReconcileSnapshot, AgentdError> {
        self.require_effect_ready()?;
        let store = self
            .automation
            .lock()
            .map_err(poisoned_state)?
            .clone()
            .ok_or_else(|| AgentdError::Protocol(AUTOMATION_UNAVAILABLE_MESSAGE.to_owned()))?;
        let host = self.automation_effect_host().ok_or_else(|| {
            AgentdError::Protocol(AUTOMATION_EFFECT_UNAVAILABLE_MESSAGE.to_owned())
        })?;
        let result = host.observe_terminal(&store, intent, command_id).await?;
        self.require_effect_ready()?;
        use crate::automation_effect_host::AgentdAutomationEffectReconcileOutcome as Outcome;
        match result {
            Outcome::Observed { receipt, chain } => Ok(crate::AutomationEffectReconcileSnapshot {
                state: crate::AutomationEffectReconcileState::Terminal,
                effect: Some(effect_snapshot(*receipt)?),
                chain: chain.map(|chain| *chain),
            }),
            Outcome::Indeterminate => Ok(crate::AutomationEffectReconcileSnapshot {
                state: crate::AutomationEffectReconcileState::Indeterminate,
                effect: None,
                chain: None,
            }),
            Outcome::ProvenAbsent => Err(AgentdError::Protocol(
                "terminal read cannot prove absence".to_owned(),
            )),
        }
    }
}

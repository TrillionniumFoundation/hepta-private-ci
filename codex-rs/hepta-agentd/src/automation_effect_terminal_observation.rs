use super::*;

impl AgentdAutomationEffectHost {
    pub(crate) async fn observe_terminal(
        &self,
        store: &AutomationStore,
        intent: &AuthorizedEffectIntent,
        command_id: &str,
    ) -> Result<AgentdAutomationEffectReconcileOutcome, AgentdError> {
        self.refresh_revocations()?;
        self.validate_subject(intent)?;
        // The original owner validates intent, command and FinalUse binding
        // before durable material can be used for a provider observation.
        let Some(receipt) = store
            .read_authorized_taskflow_effect_receipt(intent, command_id)
            .await
            .map_err(|error| AgentdError::Protocol(error.to_string()))?
        else {
            return Ok(AgentdAutomationEffectReconcileOutcome::Indeterminate);
        };
        let Some(pending) = store
            .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
            .await
            .map_err(|error| AgentdError::Protocol(error.to_string()))?
        else {
            return Ok(AgentdAutomationEffectReconcileOutcome::Indeterminate);
        };
        let bytes = pending.wire_payload.as_deref().ok_or_else(|| {
            AgentdError::Protocol("terminal effect has no durable exact wire material".to_owned())
        })?;
        let profile = if self.pon_packet_files_enabled() {
            EffectMaterialProfile::PonPacket
        } else {
            EffectMaterialProfile::Inline
        };
        self.validate_intent(intent, bytes, profile)?;
        let provider_intent = self.provider_intent(&pending)?;
        let chain = self
            .adapter
            .current_chain_observation(&provider_intent, Some(bytes))
            .await;
        Ok(AgentdAutomationEffectReconcileOutcome::Observed {
            receipt: Box::new(receipt),
            chain: chain.map(Box::new),
        })
    }
}

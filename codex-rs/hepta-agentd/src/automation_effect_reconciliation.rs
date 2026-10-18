//! Reconciliation of an existing immutable attempt. No lease or grant is minted.
use super::*;

impl AgentdAutomationEffectHost {
    async fn reconcile_pending(
        &self,
        store: &AutomationStore,
        pending: &AuthorizedEffectPending,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<AgentdAutomationEffectReconcileOutcome, AgentdError> {
        let run_id = pending.run_id.as_str();
        let step_id = pending.step_id.as_str();
        let attempt = pending.attempt;
        if let Some(local) = store
            .settle_authorized_taskflow_effect_observation(run_id, step_id, attempt, fence)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!(
                    "settle durable authorized effect observation: {error}"
                ))
            })?
        {
            match local {
                AuthorizedEffectRecoveryResult::Observed(receipt)
                    if receipt.final_outcome.is_some()
                        || receipt.observation != Some(TaskFlowStepObservation::Indeterminate) =>
                {
                    let provider_intent = self.provider_intent(pending)?;
                    let chain = self
                        .adapter
                        .current_chain_observation(
                            &provider_intent,
                            pending.wire_payload.as_deref(),
                        )
                        .await;
                    return Ok(AgentdAutomationEffectReconcileOutcome::Observed {
                        receipt,
                        chain: chain.map(Box::new),
                    });
                }
                AuthorizedEffectRecoveryResult::ProvenAbsent => {
                    return Ok(AgentdAutomationEffectReconcileOutcome::ProvenAbsent);
                }
                AuthorizedEffectRecoveryResult::Observed(_) => {}
            }
        }
        let provider_intent = self.provider_intent(pending)?;
        match self
            .adapter
            .lookup_for_reconciliation(&provider_intent, pending.wire_payload.as_deref())
            .await
        {
            ProviderEffectLookup::Ack(ack) => {
                let Some(receipt) = terminal_receipt_from_ack(&ack) else {
                    return Ok(AgentdAutomationEffectReconcileOutcome::Indeterminate);
                };
                match store
                    .recover_authorized_taskflow_effect(
                        run_id,
                        step_id,
                        attempt,
                        fence,
                        AuthorizedEffectRecovery::Observed(receipt),
                        now_ms,
                    )
                    .await
                    .map_err(|error| {
                        AgentdError::Protocol(format!(
                            "reconcile authorized effect terminal observation: {error}"
                        ))
                    })? {
                    AuthorizedEffectRecoveryResult::Observed(receipt) => {
                        let chain = self
                            .adapter
                            .current_chain_observation(
                                &provider_intent,
                                pending.wire_payload.as_deref(),
                            )
                            .await;
                        Ok(AgentdAutomationEffectReconcileOutcome::Observed {
                            receipt,
                            chain: chain.map(Box::new),
                        })
                    }
                    AuthorizedEffectRecoveryResult::ProvenAbsent => Err(AgentdError::Protocol(
                        "status lookup cannot manufacture provider absence".to_string(),
                    )),
                }
            }
            ProviderEffectLookup::Conflict { .. } => Err(AgentdError::Protocol(
                "provider reports a same-key payload conflict".to_string(),
            )),
            ProviderEffectLookup::NotFound | ProviderEffectLookup::Unknown => {
                Ok(AgentdAutomationEffectReconcileOutcome::Indeterminate)
            }
        }
    }
}

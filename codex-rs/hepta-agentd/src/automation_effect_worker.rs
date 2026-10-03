//! Host-owned, bounded provider workers retain authority across caller cancellation.

use super::*;

impl AgentdAutomationEffectHost {
    pub(crate) fn reserve_provider_effect(
        &self,
    ) -> Result<AgentdAutomationEffectReservation, AgentdError> {
        let host_slots = Arc::clone(&self.provider_workers);
        let permit = Arc::clone(&host_slots).try_acquire_owned().map_err(|_| {
            AgentdError::Protocol("automation provider worker bound exhausted".to_string())
        })?;
        Ok(AgentdAutomationEffectReservation { host_slots, permit })
    }

    fn consume_provider_reservation(
        &self,
        reservation: AgentdAutomationEffectReservation,
    ) -> Result<OwnedSemaphorePermit, AgentdError> {
        if !Arc::ptr_eq(&reservation.host_slots, &self.provider_workers) {
            return Err(AgentdError::GenerationFenced(
                "automation provider reservation belongs to a different host".to_string(),
            ));
        }
        Ok(reservation.permit)
    }

    /// Occupied host slots include admitted work waiting for a blocking worker
    /// and physical provider workers detached from cancelled control callers.
    pub(crate) fn pending_effect_workers(&self) -> u32 {
        u32::try_from(MAX_PROVIDER_WORKERS - self.provider_workers.available_permits())
            .unwrap_or(u32::MAX)
    }

    #[cfg(test)]
    pub(crate) async fn execute(
        &self,
        store: &AutomationStore,
        intent: &AuthorizedEffectIntent,
        wire_payload: &[u8],
        signed_grant: &SignedFinalUseGrant,
        command_id: &str,
        now_ms: u64,
    ) -> Result<TaskFlowStepReceipt, AgentdError> {
        let reservation = self.reserve_provider_effect()?;
        self.execute_reserved(
            reservation,
            store,
            intent,
            wire_payload,
            signed_grant,
            command_id,
            now_ms,
        )
        .await
    }

    #[expect(
        clippy::too_many_arguments,
        reason = "the reserved effect boundary keeps the owner store and exact signed dispatch inputs explicit"
    )]
    pub(crate) async fn execute_reserved(
        &self,
        reservation: AgentdAutomationEffectReservation,
        store: &AutomationStore,
        intent: &AuthorizedEffectIntent,
        wire_payload: &[u8],
        signed_grant: &SignedFinalUseGrant,
        command_id: &str,
        _now_ms: u64,
    ) -> Result<TaskFlowStepReceipt, AgentdError> {
        let permit = self.consume_provider_reservation(reservation)?;
        self.validate_intent(intent, wire_payload)?;
        self.refresh_revocations()?;
        if let Some(receipt) = store
            .read_authorized_taskflow_effect_receipt(intent, command_id)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!("read terminal effect receipt: {error}"))
            })?
        {
            return Ok(receipt);
        }
        let host = self.clone();
        let store = store.clone();
        let intent = intent.clone();
        let wire_payload = wire_payload.to_vec();
        let signed_grant = signed_grant.clone();
        let command_id = command_id.to_string();
        // The complete owner bridge stays inside this bounded worker. A
        // cancelled control caller only stops awaiting it: the worker retains
        // both its quota and the final-use dispatch guard until the provider
        // observation has been recorded or durable uncertainty remains.
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .map_err(|_| AgentdError::Protocol("automation provider worker runtime unavailable".to_string()))?;
            runtime.block_on(async move {
                // Revalidate after blocking-pool scheduling, before claiming
                // authority or contacting the provider.
                host.refresh_revocations()?;
                let run = store
                    .taskflow_run(&intent.run_id)
                    .await
                    .map_err(|error| AgentdError::Protocol(format!("read effect TaskFlow run: {error}")))?
                    .ok_or_else(|| AgentdError::Invalid("effect TaskFlow run does not exist".to_string()))?;
                let now_ms = crate::automation::unix_time_ms()?;
                let fence = host.current_fence(&run, now_ms)?;
                let binding = intent
                    .final_use_binding()
                    .map_err(|error| AgentdError::Invalid(error.to_string()))?;
                let mut driver = HttpAuthorizedEffectDriver {
                    adapter: host.adapter.clone(),
                    provider_scope: host.provider_scope.clone(),
                    destination_id: host.destination_id.clone(),
                };
                store
                    .execute_authorized_taskflow_effect(
                        &host.authority,
                        &mut driver,
                        &intent,
                        &wire_payload,
                        &fence,
                        &signed_grant,
                        &binding,
                        &command_id,
                        now_ms,
                    )
                    .await
                    .map_err(|error| AgentdError::Protocol(format!("automation authorized effect dispatch: {error}")))
            })
        })
        .await
        .map_err(|_| AgentdError::Protocol("automation provider worker exited without a durable acknowledgement; reconciliation is required".to_string()))?
    }

    #[cfg(test)]
    pub(crate) async fn reconcile(
        &self,
        store: &AutomationStore,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        now_ms: u64,
    ) -> Result<AgentdAutomationEffectReconcileOutcome, AgentdError> {
        let Ok(reservation) = self.reserve_provider_effect() else {
            return Ok(AgentdAutomationEffectReconcileOutcome::Indeterminate);
        };
        self.reconcile_reserved(reservation, store, run_id, step_id, attempt, now_ms)
            .await
    }

    pub(crate) async fn reconcile_reserved(
        &self,
        reservation: AgentdAutomationEffectReservation,
        store: &AutomationStore,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        now_ms: u64,
    ) -> Result<AgentdAutomationEffectReconcileOutcome, AgentdError> {
        let permit = self.consume_provider_reservation(reservation)?;
        let pending = store
            .authorized_taskflow_effect_attempt(run_id, step_id, attempt)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!("read pending authorized effect: {error}"))
            })?
            .ok_or_else(|| {
                AgentdError::Invalid("authorized effect is not pending reconciliation".to_string())
            })?;
        if pending.destination_id != self.destination_id {
            return Err(AgentdError::GenerationFenced(
                "pending effect destination differs from the configured provider".to_string(),
            ));
        }
        let run = store
            .taskflow_run(run_id)
            .await
            .map_err(|error| AgentdError::Protocol(format!("read effect TaskFlow run: {error}")))?
            .ok_or_else(|| {
                AgentdError::Invalid("effect TaskFlow run does not exist".to_string())
            })?;
        let fence = self.current_fence(&run, now_ms)?;
        if let Some(local) = store
            .settle_authorized_taskflow_effect_observation(run_id, step_id, attempt, &fence)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!(
                    "settle durable authorized effect observation: {error}"
                ))
            })?
        {
            match local {
                AuthorizedEffectRecoveryResult::Observed(receipt)
                    if receipt.observation != Some(TaskFlowStepObservation::Indeterminate) =>
                {
                    return Ok(AgentdAutomationEffectReconcileOutcome::Observed(*receipt));
                }
                AuthorizedEffectRecoveryResult::ProvenAbsent => {
                    return Ok(AgentdAutomationEffectReconcileOutcome::ProvenAbsent);
                }
                AuthorizedEffectRecoveryResult::Observed(_) => {}
            }
        }
        let provider_intent = self.provider_intent(&pending)?;
        let adapter = self.adapter.clone();
        let lookup = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let Ok(runtime) = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
            else {
                return ProviderEffectLookup::Unknown;
            };
            runtime.block_on(adapter.lookup_for_intent(&provider_intent))
        })
        .await
        .unwrap_or(ProviderEffectLookup::Unknown);
        match lookup {
            ProviderEffectLookup::Ack(ack) => {
                let Some(receipt) = terminal_receipt_from_ack(&ack) else {
                    return Ok(AgentdAutomationEffectReconcileOutcome::Indeterminate);
                };
                // Provider observation can outlast the owner lease. Let the
                // durable owner validate the original fence at observation
                // time, rather than treating the pre-request time as current.
                let observed_at_ms = crate::automation::unix_time_ms()?;
                match store
                    .recover_authorized_taskflow_effect(
                        run_id,
                        step_id,
                        attempt,
                        &fence,
                        AuthorizedEffectRecovery::Observed(receipt),
                        observed_at_ms,
                    )
                    .await
                    .map_err(|error| {
                        AgentdError::Protocol(format!(
                            "reconcile authorized effect terminal observation: {error}"
                        ))
                    })? {
                    AuthorizedEffectRecoveryResult::Observed(receipt) => {
                        Ok(AgentdAutomationEffectReconcileOutcome::Observed(*receipt))
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

    fn refresh_revocations(&self) -> Result<(), AgentdError> {
        let head = read_revocations_file(&self.revocations_file)?;
        let mut frontier = self.revocation_frontier.lock().map_err(|_| {
            AgentdError::Protocol(
                "automation effect revocation frontier lock is poisoned".to_string(),
            )
        })?;
        let observed = (head.authority_epoch, head.revision);
        let trusted = (frontier.authority_epoch, frontier.revision);
        if observed == trusted {
            if head == *frontier {
                return Ok(());
            }
            return Err(AgentdError::GenerationFenced(
                "automation effect revocation head changed without advancing its frontier"
                    .to_string(),
            ));
        }
        if observed.0 < trusted.0 || (observed.0 == trusted.0 && observed.1 < trusted.1) {
            return Err(AgentdError::GenerationFenced(
                "automation effect revocation frontier rolled back".to_string(),
            ));
        }
        self.authority
            .update_revocations(head.clone())
            .map_err(|error| {
                AgentdError::GenerationFenced(format!(
                    "automation effect revocation refresh rejected: {error}"
                ))
            })?;
        *frontier = head;
        Ok(())
    }
}

//! Supervised delivery of one explicitly registered completed Circuit task.
//! The host supplies the exact request, original stage owners and checkpoint;
//! this consumer cannot provision them or infer authority from the outbox.

use codex_hepta_automation::AutomationStore;

use super::*;

pub(crate) struct CircuitLearningDeliveryRuntimeV1 {
    handle: LearningIterationHandleV1,
    spawn_generation: u64,
    pub(crate) request: LearningIterationRequestV1,
    owners: LearningIterationOwnersV1,
}

impl LearningIterationRuntimeBootstrapV1 {
    /// Connect this owner's exact request to ordinary Circuit completion.
    /// The ordinary runtime requires its Circuit profile and governed
    /// plasticity owner, then supervises delivery beside this same worker.
    /// The retained sender prevents dropping the returned external handle from
    /// silently disconnecting delivery. No second queue or owner is created.
    ///
    /// This is a one-iteration host composition, not a descriptor loader or a
    /// general training scheduler. A claimed operation without a recoverable
    /// checkpoint stays pending; absence is never permission to train again.
    pub fn with_circuit_learning_delivery(
        mut self,
        request: LearningIterationRequestV1,
    ) -> Result<Self, AgentdError> {
        if self.circuit_delivery_request.is_some() {
            return Err(AgentdError::Invalid(
                "Circuit learning delivery already configured".into(),
            ));
        }
        if request.agent_id.as_str() != self.agent_id.as_str() {
            return Err(AgentdError::GenerationFenced(
                "Circuit learning request belongs to another agent".into(),
            ));
        }
        self.require_frozen_scope(&request)
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        LearningIterationCoordinatorV1::new(request.clone(), self.owners.clone())
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        self.circuit_delivery_request = Some(request);
        self.enforce_circuit_admission = true;
        Ok(self)
    }

    pub(crate) fn take_circuit_delivery(&mut self) -> Option<CircuitLearningDeliveryRuntimeV1> {
        self.circuit_delivery_request
            .take()
            .map(|request| CircuitLearningDeliveryRuntimeV1 {
                handle: LearningIterationHandleV1 {
                    sender: self.sender.clone(),
                },
                spawn_generation: self.spawn_generation,
                request,
                owners: self.owners.clone(),
            })
    }
}

impl CircuitLearningDeliveryRuntimeV1 {
    pub(crate) async fn run(
        self,
        store: AutomationStore,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        if store.owner_agent_id().as_str() != self.request.agent_id.as_str()
            || state.identity().agent_id.as_str() != self.request.agent_id.as_str()
            || state.identity().spawn_generation != self.spawn_generation
        {
            return Err(AgentdError::GenerationFenced(
                "Circuit learning delivery owner differs".into(),
            ));
        }
        let mut interval = tokio::time::interval(Duration::from_secs(1));
        interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        loop {
            tokio::select! {
                _ = cancellation.cancelled() => return Ok(()),
                _ = interval.tick() => {}
            }
            // Readback retains the existing learning lifecycle boundary.
            // Fresh claims below additionally require full ordinary admission.
            if require_ready(&state).is_err() {
                continue;
            }
            let row = tokio::select! {
                _ = cancellation.cancelled() => return Ok(()),
                row = store.circuit_learning_delivery(self.request.source_run_id.as_str()) => row,
            }
            .map_err(|error| {
                AgentdError::Protocol(format!("Circuit learning outbox: {error:?}"))
            })?;
            let Some(row) = row else {
                continue;
            };
            let claimed = row.request_digest.is_some();
            if !claimed && !state.automation_admission_ready()? {
                continue;
            }
            let delivery = async {
                if claimed {
                    crate::reconcile_circuit_learning_v1(
                        &store,
                        Some(&self.handle),
                        self.request.clone(),
                        self.owners.clone(),
                    )
                    .await
                } else {
                    crate::deliver_circuit_learning_v1(
                        &store,
                        Some(&self.handle),
                        self.request.clone(),
                        self.owners.clone(),
                    )
                    .await
                }
            };
            let result = tokio::select! {
                _ = cancellation.cancelled() => return Ok(()),
                result = delivery => result,
            };
            match result {
                Ok(_) => {
                    // A required supervised service must not exit merely
                    // because its one exact delivery has been acknowledged.
                    cancellation.cancelled().await;
                    return Ok(());
                }
                Err(
                    LearningIterationRuntimeErrorV1::CommitUncertain
                    | LearningIterationRuntimeErrorV1::Unavailable
                    | LearningIterationRuntimeErrorV1::QueueFull,
                ) => {}
                Err(error) => {
                    // Missing mandatory owners, invalid evidence or expired
                    // new work is a refused configured service, not a retry.
                    return Err(AgentdError::Protocol(format!(
                        "Circuit learning delivery refused: {error}"
                    )));
                }
            }
        }
    }
}

//! Supervised serial delivery of explicitly registered completed Circuit tasks.
//! The host supplies the exact request, original stage owners and checkpoint;
//! this consumer cannot provision them or infer authority from the outbox.

use codex_hepta_automation::AutomationStore;

use super::*;

#[derive(Clone, Copy)]
pub(crate) enum CircuitLearningSourceV1 {
    HostStageOwners,
    OriginalObjective,
    OriginalQ24,
}

impl CircuitLearningSourceV1 {
    fn requires_original_objective(self) -> bool {
        match self {
            Self::HostStageOwners => false,
            Self::OriginalObjective | Self::OriginalQ24 => true,
        }
    }
}

pub(crate) struct CircuitLearningDeliveryRuntimeV1 {
    handle: LearningIterationHandleV1,
    spawn_generation: u64,
    pub(crate) requests: Vec<LearningIterationRequestV1>,
    owners: LearningIterationOwnersV1,
    source: CircuitLearningSourceV1,
    #[cfg(target_os = "linux")]
    retained_source: Option<Arc<crate::cell_q24_task_ledger::RegisteredCellQ24RetainedSourceV1>>,
}

impl LearningIterationRuntimeBootstrapV1 {
    /// Only the original Root-capability consumer selects this mandatory
    /// Objective/Circuit source join. The generic host-owned channel retains
    /// its existing explicit stage-owner contract.
    pub(crate) fn with_original_circuit_learning_delivery(
        self,
        request: LearningIterationRequestV1,
    ) -> Result<Self, AgentdError> {
        let mut bootstrap = self.with_circuit_learning_delivery(request)?;
        bootstrap.circuit_delivery_source = CircuitLearningSourceV1::OriginalObjective;
        Ok(bootstrap)
    }

    /// Connect this owner's exact request to ordinary Circuit completion.
    /// The ordinary runtime requires its Circuit profile and governed
    /// plasticity owner, then supervises delivery beside this same worker.
    /// The retained sender prevents dropping the returned external handle from
    /// silently disconnecting delivery. No second queue or owner is created.
    ///
    /// This remains an explicit host composition. A claimed operation without
    /// a recoverable checkpoint stays pending; absence is never retry permission.
    pub fn with_circuit_learning_delivery(
        self,
        request: LearningIterationRequestV1,
    ) -> Result<Self, AgentdError> {
        self.with_circuit_learning_registry(CircuitLearningDeliveryRegistryV1::new(vec![request])?)
    }

    /// Register a bounded set without inferring successor requests. The host's
    /// existing ports must recover each exact operation; all original scope,
    /// receipt, checkpoint and current-authority checks remain in the worker.
    pub fn with_circuit_learning_registry(
        mut self,
        registry: CircuitLearningDeliveryRegistryV1,
    ) -> Result<Self, AgentdError> {
        if self.circuit_delivery_registry.is_some() {
            return Err(AgentdError::Invalid(
                "Circuit learning delivery already configured".into(),
            ));
        }
        for request in &registry.requests {
            self.require_frozen_scope(request)
                .map_err(|error| AgentdError::Invalid(error.to_string()))?;
            if request.agent_id.as_str() != self.agent_id.as_str() {
                return Err(AgentdError::GenerationFenced(
                    "Circuit learning request belongs to another agent".into(),
                ));
            }
            LearningIterationCoordinatorV1::new(request.clone(), self.owners.clone())
                .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        }
        self.circuit_delivery_registry = Some(registry);
        self.enforce_circuit_admission = true;
        Ok(self)
    }

    pub(crate) fn take_circuit_delivery(&mut self) -> Option<CircuitLearningDeliveryRuntimeV1> {
        self.circuit_delivery_registry
            .take()
            .map(|registry| CircuitLearningDeliveryRuntimeV1 {
                handle: LearningIterationHandleV1 {
                    sender: self.sender.clone(),
                },
                spawn_generation: self.spawn_generation,
                requests: registry.requests,
                owners: self.owners.clone(),
                source: self.circuit_delivery_source,
                #[cfg(target_os = "linux")]
                retained_source: self.retained_source.take(),
            })
    }
}

impl CircuitLearningDeliveryRuntimeV1 {
    pub(crate) fn attach_sources(&self, state: &AgentdState) -> Result<(), AgentdError> {
        #[cfg(target_os = "linux")]
        if let Some(source) = &self.retained_source {
            return state.attach_original_retained_learning_source(Arc::clone(source));
        }
        state.attach_circuit_learning_delivery(
            self.requests
                .iter()
                .map(|request| request.source_run_id.clone())
                .collect(),
            self.source,
        )
    }

    pub(crate) async fn run(
        self,
        store: AutomationStore,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        #[cfg(target_os = "linux")]
        let store = if let Some(source) = &self.retained_source {
            let source: &Arc<crate::cell_q24_task_ledger::RegisteredCellQ24RetainedSourceV1> =
                source;
            source.observe_retained_learning(state.identity()).await?;
            if self.requests.as_slice() != std::slice::from_ref(source.request()) {
                return Err(AgentdError::GenerationFenced(
                    "original retained delivery request differs".into(),
                ));
            }
            source.original_outbox(state.identity(), source.request())?
        } else {
            store
        };
        if self.requests.iter().any(|request| {
            store.owner_agent_id().as_str() != request.agent_id.as_str()
                || state.identity().agent_id.as_str() != request.agent_id.as_str()
        }) || state.identity().spawn_generation != self.spawn_generation
        {
            return Err(AgentdError::GenerationFenced(
                "Circuit learning delivery owner differs".into(),
            ));
        }
        let mut interval = tokio::time::interval(Duration::from_secs(1));
        interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        let mut completed = vec![false; self.requests.len()];
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
            for (index, request) in self.requests.iter().enumerate() {
                if completed[index] {
                    continue;
                }
                let row = tokio::select! {
                    _ = cancellation.cancelled() => return Ok(()),
                    row = store.circuit_learning_delivery(request.source_run_id.as_str()) => row,
                }
                .map_err(|error| {
                    AgentdError::Protocol(format!("Circuit learning outbox: {error:?}"))
                })?;
                let Some(row) = row else {
                    continue;
                };
                // A crash between the original ACK and retirement must not require
                // renewed stage signatures merely to release this local slot.
                // Exact historical ACK cleanup publishes no learning snapshot.
                if row.acknowledged_head.is_some() {
                    let retirement = crate::circuit_learning_delivery::retire_acknowledged_delivery(
                        &store,
                        request,
                        &self.owners,
                        &row,
                    );
                    let result = tokio::select! {
                        _ = cancellation.cancelled() => return Ok(()),
                        result = retirement => result,
                    };
                    match result {
                        Ok(()) => completed[index] = true,
                        Err(LearningIterationRuntimeErrorV1::CommitUncertain) => {}
                        Err(error) => {
                            return Err(AgentdError::Protocol(format!(
                                "Circuit learning ACK retirement refused: {error}"
                            )));
                        }
                    }
                    continue;
                }
                let claimed = row.request_digest.is_some();
                if !claimed && !state.automation_admission_ready()? {
                    continue;
                }
                if !claimed && self.source.requires_original_objective() {
                    tokio::select! {
                        _ = cancellation.cancelled() => return Ok(()),
                        result = state.require_circuit_learning_source(request) => result?,
                    }
                }
                let delivery = async {
                    if claimed {
                        crate::reconcile_circuit_learning_v1(
                            &store,
                            Some(&self.handle),
                            request.clone(),
                            self.owners.clone(),
                        )
                        .await
                    } else if self.source.requires_original_objective() {
                        // Reauthenticate the same original owners after the durable
                        // claim, before any stage dispatch. The registered list
                        // grants no replacement Objective or Circuit authority.
                        let source_state: Arc<AgentdState> = Arc::clone(&state);
                        let source_request = request.clone();
                        crate::circuit_learning_delivery::deliver_circuit_learning_with_post_claim_source_v1(
                            &store,
                            Some(&self.handle),
                            request.clone(),
                            self.owners.clone(),
                            Box::pin(async move {
                                source_state
                                    .require_circuit_learning_source(&source_request)
                                    .await
                                    .map_err(|_| LearningIterationRuntimeErrorV1::WrongScope)
                            }),
                        )
                        .await
                    } else {
                        crate::deliver_circuit_learning_v1(
                            &store,
                            Some(&self.handle),
                            request.clone(),
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
                        completed[index] = true;
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
            if completed.iter().all(|completed| *completed) {
                cancellation.cancelled().await;
                return Ok(());
            }
        }
    }
}

#[cfg(target_os = "linux")]
#[path = "learning_iteration_delivery_same_actor.rs"]
mod same_actor;
#[cfg(target_os = "linux")]
pub(crate) use same_actor::OriginalLearningDeliveryRetired;

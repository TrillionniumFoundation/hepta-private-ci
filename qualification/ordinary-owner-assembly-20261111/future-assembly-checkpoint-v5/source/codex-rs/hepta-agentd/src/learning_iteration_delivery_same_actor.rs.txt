//! Normal retirement of the actual one-request retained-A delivery owner.
//! A local completed flag or cancellation result never constructs the ACK.

use super::*;
use crate::circuit_learning_delivery::OriginalDurableLearningAcknowledgement;
use crate::circuit_learning_delivery::deliver_original_same_actor_ack;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
use crate::same_actor_q24_phase_learning::OriginalSameActorLearningWork;

pub(crate) struct OriginalLearningDeliveryRetired {
    // Drop closes the common Gate before releasing the retained delivery owner.
    _closing: CloseSameActorPhaseOnDrop,
    runtime: CircuitLearningDeliveryRuntimeV1,
    acknowledged: OriginalDurableLearningAcknowledgement,
}

struct OriginalRetirableDeliveryAttempt {
    closing: CloseSameActorPhaseOnDrop,
    runtime: CircuitLearningDeliveryRuntimeV1,
    store: AutomationStore,
    state: Arc<AgentdState>,
    cancellation: CancellationToken,
    work: Arc<OriginalSameActorLearningWork>,
}

impl OriginalLearningDeliveryRetired {
    pub(crate) fn acknowledgement(&self) -> &OriginalDurableLearningAcknowledgement {
        &self.acknowledged
    }

    pub(crate) fn require_original_work(
        &self,
        work: &Arc<OriginalSameActorLearningWork>,
    ) -> Result<(), AgentdError> {
        OriginalDurableLearningAcknowledgement::require_original_work(&self.acknowledged, work)?;
        let snapshot = self.acknowledged.snapshot();
        if self.runtime.requests.as_slice() != std::slice::from_ref(&snapshot.request)
            || self.runtime.owners != snapshot.owners
            || !matches!(self.runtime.source, CircuitLearningSourceV1::OriginalQ24)
            || self.runtime.retained_source.is_none()
        {
            work.gate().close();
            return Err(refused("retired delivery owner differs from its actual ACK"));
        }
        Ok(())
    }
}

impl CircuitLearningDeliveryRuntimeV1 {
    pub(crate) fn run_original_retirable(
        self,
        store: AutomationStore,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
        work: Arc<OriginalSameActorLearningWork>,
    ) -> impl std::future::Future<Output = Result<OriginalLearningDeliveryRetired, AgentdError>>
    + Send
    + 'static {
        let attempt = OriginalRetirableDeliveryAttempt {
            closing: work.original_failure_scope(),
            runtime: self,
            store,
            state,
            cancellation,
            work,
        };
        async move {
            // Retain the real runtime and its failure guard even before poll.
            let attempt = attempt;
            let acknowledged = CircuitLearningDeliveryRuntimeV1::run_original_ack(
                &attempt.runtime,
                attempt.store,
                &attempt.state,
                &attempt.cancellation,
                &attempt.work,
            ).await?;
            if attempt.cancellation.is_cancelled() {
                return Err(refused("delivery fault cancellation after durable ACK"));
            }
            OriginalDurableLearningAcknowledgement::require_original_work(
                &acknowledged, &attempt.work,
            )?;
            Ok(OriginalLearningDeliveryRetired {
                _closing: attempt.closing,
                runtime: attempt.runtime,
                acknowledged,
            })
        }
    }

    async fn run_original_ack(
        &self,
        store: AutomationStore,
        state: &Arc<AgentdState>,
        cancellation: &CancellationToken,
        work: &Arc<OriginalSameActorLearningWork>,
    ) -> Result<OriginalDurableLearningAcknowledgement, AgentdError> {
        work.require_identity_and_gate(state.identity(), work.gate())?;
        if self.requests.len() != 1
            || !matches!(self.source, CircuitLearningSourceV1::OriginalQ24)
            || state.identity().spawn_generation != self.spawn_generation
        {
            return Err(refused("normal retirement requires the actual retained-A delivery"));
        }
        let source: &Arc<crate::cell_q24_task_ledger::RegisteredCellQ24RetainedSourceV1> =
            self.retained_source.as_ref()
                .ok_or_else(|| refused("actual retained-A source is absent"))?;
        source.observe_retained_learning(state.identity()).await?;
        let request = self.requests[0].clone();
        if &request != source.request() {
            return Err(refused("retained-A delivery request changed"));
        }
        let original_store = source.original_outbox(state.identity(), &request)?;
        // The original retained source selects the same actual outbox as the
        // default worker; an unrelated supplied store cannot replace it.
        drop(store);
        if original_store.owner_agent_id().as_str() != request.agent_id.as_str()
            || state.identity().agent_id.as_str() != request.agent_id.as_str()
        {
            return Err(refused("original delivery outbox or identity changed"));
        }
        work.require_original_delivery_request(&request, &self.owners)?;
        let mut interval = tokio::time::interval(Duration::from_secs(1));
        interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        loop {
            tokio::select! {
                _ = cancellation.cancelled() => return Err(refused("delivery fault cancellation")),
                _ = work.gate().cancelled() => return Err(refused("original delivery phase closed")),
                _ = tokio::time::sleep_until(tokio::time::Instant::from_std(
                    work.gate().deadline().instant(),
                )) => return Err(refused("original delivery phase ended")),
                _ = interval.tick() => {},
            }
            work.require_original_delivery_request(&request, &self.owners)?;
            if require_ready(state).is_err() {
                continue;
            }
            let row = tokio::select! {
                _ = cancellation.cancelled() => return Err(refused("delivery fault cancellation")),
                _ = work.gate().cancelled() => return Err(refused("original delivery phase closed")),
                _ = tokio::time::sleep_until(tokio::time::Instant::from_std(
                    work.gate().deadline().instant(),
                )) => return Err(refused("original delivery phase ended")),
                row = original_store.circuit_learning_delivery(request.source_run_id.as_str()) =>
                    row.map_err(|error| refused(format!("original Circuit outbox: {error:?}")))?,
            };
            let Some(row) = row else {
                continue;
            };
            if row.request_digest.is_none() {
                if !state.automation_admission_ready()? {
                    continue;
                }
                // Preserve the original pre-claim Objective/Circuit check as
                // well as the concrete post-claim check inside delivery.
                tokio::select! {
                    _ = cancellation.cancelled() =>
                        return Err(refused("delivery fault cancellation before original claim")),
                    _ = work.gate().cancelled() =>
                        return Err(refused("original delivery phase closed before claim")),
                    _ = tokio::time::sleep_until(tokio::time::Instant::from_std(
                        work.gate().deadline().instant(),
                    )) => return Err(refused("original delivery phase ended before claim")),
                    result = AgentdState::require_circuit_learning_source(state, &request) => result?,
                };
            }
            // Attempt exactly once. The original function permits readback
            // for a previous claim; uncertainty never becomes a fresh dispatch.
            let acknowledged = tokio::select! {
                _ = cancellation.cancelled() => return Err(refused("delivery fault cancellation")),
                _ = work.gate().cancelled() => return Err(refused("original delivery phase closed")),
                _ = tokio::time::sleep_until(tokio::time::Instant::from_std(
                    work.gate().deadline().instant(),
                )) => return Err(refused("original delivery phase ended")),
                result = deliver_original_same_actor_ack(
                    &original_store, &self.handle, request.clone(), self.owners.clone(),
                    Arc::clone(state), Arc::clone(work),
                ) => result?,
            };
            OriginalDurableLearningAcknowledgement::require_original_work(&acknowledged, work)?;
            return Ok(acknowledged);
        }
    }
}

fn refused(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::GenerationFenced(error.to_string())
}

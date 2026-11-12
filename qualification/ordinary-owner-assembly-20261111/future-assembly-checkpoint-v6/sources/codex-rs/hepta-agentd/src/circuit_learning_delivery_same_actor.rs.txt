//! Durable learning acknowledgement from the original concrete delivery.
//! The constructor is private to this module and follows the actual original
//! checkpoint response, durable ACK transaction and exact local retirement.

use super::*;
use std::sync::Arc;
use crate::AgentdError;
use crate::AgentdState;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
use crate::same_actor_q24_phase_learning::OriginalSameActorLearningWork;

pub(crate) struct OriginalDurableLearningAcknowledgement {
    _closing: CloseSameActorPhaseOnDrop,
    work: Arc<OriginalSameActorLearningWork>,
    snapshot: LearningIterationSnapshotV1,
    _store: AutomationStore,
}

impl OriginalDurableLearningAcknowledgement {
    pub(crate) fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        &self.snapshot
    }

    pub(crate) fn require_original_work(
        &self,
        work: &Arc<OriginalSameActorLearningWork>,
    ) -> Result<(), AgentdError> {
        if !Arc::ptr_eq(&self.work, work) {
            self.work.gate().close();
            work.gate().close();
            return Err(AgentdError::GenerationFenced(
                "durable delivery ACK belongs to another original Work".into(),
            ));
        }
        work.require_original_terminal_snapshot(&self.snapshot)
    }
}

pub(crate) async fn deliver_original_same_actor_ack(
    store: &AutomationStore,
    backend: &LearningIterationHandleV1,
    request: LearningIterationRequestV1,
    owners: LearningIterationOwnersV1,
    state: Arc<AgentdState>,
    work: Arc<OriginalSameActorLearningWork>,
) -> Result<OriginalDurableLearningAcknowledgement, AgentdError> {
    let closing = work.original_failure_scope();
    work.require_identity_and_gate(state.identity(), work.gate())?;
    work.require_original_delivery_request(&request, &owners)?;
    let source_state: Arc<AgentdState> = Arc::clone(&state);
    let source_request = request.clone();
    let source_work: Arc<OriginalSameActorLearningWork> = Arc::clone(&work);
    // This is the existing concrete delivery: its false claim result permits
    // only original readback; success requires next_stage == None, actual
    // acknowledge_circuit_learning and retire_acknowledged_circuit_learning.
    // No receipt-only public entry can construct this owning ACK.
    let snapshot = delivery(
        store,
        Some(backend),
        request,
        owners,
        DeliveryMode::FirstAttempt,
        Some(Box::pin(async move {
            source_work.require_original_work_entry()?;
            AgentdState::require_circuit_learning_source(&source_state, &source_request)
                .await.map_err(|_| Error::WrongScope)?;
            source_work.require_original_work_entry()
        })),
    )
    .await
    .map_err(|error| AgentdError::GenerationFenced(error.to_string()))?;
    work.require_original_terminal_snapshot(&snapshot)?;
    Ok(OriginalDurableLearningAcknowledgement {
        _closing: closing,
        work,
        snapshot,
        _store: store.clone(),
    })
}

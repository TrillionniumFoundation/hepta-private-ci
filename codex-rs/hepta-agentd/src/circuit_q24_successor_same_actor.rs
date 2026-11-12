//! Sealed C task parts for the same live actor and the same original phase.
//! Only the actual retained-source/Q24 bootstrap can construct these parts.
//! This is not an independent-consumer authorization or a restart capability.

use super::*;
use crate::AgentdIdentity;
use crate::LearningIterationRuntimeBootstrapV1;
use crate::root_production_inputs::OriginalQ24SuccessorSession;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
use crate::same_actor_q24_phase_gate::SameActorPhaseGate;

pub(crate) struct OriginalSameActorSuccessorTaskParts {
    context: Arc<OriginalQ24SuccessorContext>,
    gate: Arc<SameActorPhaseGate>,
    slot: Arc<SuccessorSlot>,
    invocation: Arc<dyn crate::AgentdCircuitTaskInvocationProviderV1>,
    phase_close: CloseSameActorPhaseOnDrop,
    slot_close: CloseOnDrop,
}

impl OriginalSameActorSuccessorTaskParts {
    pub(crate) fn into_task_parts(
        mut self,
        identity: &AgentdIdentity,
        gate: &Arc<SameActorPhaseGate>,
    ) -> Result<
        (
            Arc<SuccessorSlot>,
            Arc<dyn crate::AgentdCircuitTaskInvocationProviderV1>,
        ),
        AgentdError,
    > {
        if self.context.identity() != identity || !Arc::ptr_eq(&self.gate, gate) {
            return Err(AgentdError::GenerationFenced(
                "successor task parts differ from their original phase or full identity".into(),
            ));
        }
        self.context
            .session()
            .require_original_same_actor_phase(gate)?;
        self.slot
            .require_open()
            .map_err(|error| AgentdError::GenerationFenced(error.to_string()))?;
        gate.require_open()
            .map_err(|error| AgentdError::Protocol(error.to_string()))?;
        self.phase_close.disarm();
        self.slot_close.disarm();
        Ok((self.slot, self.invocation))
    }
}

/// Make the slot here and pass that very slot through the original aggregate's
/// registration. There is no external slot, provider, receipt or Ready value.
pub(crate) async fn prepare_original_same_actor_successor(
    mut learning: LearningIterationRuntimeBootstrapV1,
    identity: &AgentdIdentity,
    session: Arc<OriginalQ24SuccessorSession>,
    gate: Arc<SameActorPhaseGate>,
    capacity: usize,
) -> Result<
    (
        LearningIterationRuntimeBootstrapV1,
        PendingSuccessorOwner,
        OriginalQ24SuccessorHandoffV1,
        OriginalSameActorSuccessorTaskParts,
    ),
    AgentdError,
> {
    let mut phase_close = CloseSameActorPhaseOnDrop::new(&gate);
    session.require_original_same_actor_phase(&gate)?;
    learning.require_identity(identity)?;
    if !(1..=64).contains(&capacity) {
        return Err(AgentdError::Invalid("successor queue must be 1..64".into()));
    }
    let slot = SuccessorSlot::new_pending_slot();
    let mut slot_close = CloseOnDrop::new(&slot);
    let context = learning
        .prepare_original_successor_context(identity, session, &slot)
        .await?;
    context.session().require_original_same_actor_phase(&gate)?;
    let (sender, receiver) = oneshot::channel();
    let invocation = original_pending_successor_invocation(Arc::clone(&slot));
    let pending =
        PendingSuccessorOwner::new(Arc::clone(&context), Arc::clone(&slot), receiver, capacity);
    let handoff = OriginalQ24SuccessorHandoffV1 {
        context: Arc::clone(&context),
        slot: Arc::clone(&slot),
        sender: Some(sender),
        close: CloseOnDrop::new(&slot),
    };
    let parts = OriginalSameActorSuccessorTaskParts {
        context,
        gate: Arc::clone(&gate),
        slot: Arc::clone(&slot),
        invocation,
        phase_close: CloseSameActorPhaseOnDrop::new(&gate),
        slot_close: CloseOnDrop::new(&slot),
    };
    gate.require_open()
        .map_err(|error| AgentdError::Protocol(error.to_string()))?;
    slot_close.disarm();
    phase_close.disarm();
    Ok((learning, pending, handoff, parts))
}

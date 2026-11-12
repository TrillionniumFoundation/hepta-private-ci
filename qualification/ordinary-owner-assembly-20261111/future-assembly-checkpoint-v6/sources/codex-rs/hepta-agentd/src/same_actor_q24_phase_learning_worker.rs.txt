//! Required supervision for the original Learning, retained delivery and C.
//! Every stopped or failed lane closes the same phase, then joins real work.

use std::sync::Arc;

use codex_hepta_automation::AutomationStore;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdState;
use crate::LearningIterationRuntimeBootstrapV1;
use crate::learning_iteration_checkpoint::OriginalLearningCheckpointRetirement;
use crate::circuit_q24_successor::PendingSuccessorOwner;
use crate::learning_iteration::CircuitLearningDeliveryRuntimeV1;
use crate::root_production_inputs::same_actor_phase::OriginalSameActorRootContext;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;

use super::OriginalSameActorLearningWork;

pub(crate) struct OriginalSameActorLearningWorker {
    context: Arc<OriginalSameActorRootContext>,
    work: Arc<OriginalSameActorLearningWork>,
    checkpoint: OriginalLearningCheckpointRetirement,
    learning: LearningIterationRuntimeBootstrapV1,
    delivery: CircuitLearningDeliveryRuntimeV1,
    pending: PendingSuccessorOwner,
    _closing: CloseSameActorPhaseOnDrop,
}

enum FirstFinished {
    Learning(Result<(), AgentdError>),
    Delivery(Result<(), AgentdError>),
    Successor(Result<(), AgentdError>),
    Closed,
}

impl OriginalSameActorLearningWorker {
    pub(super) fn from_original_parts(
        context: Arc<OriginalSameActorRootContext>,
        work: Arc<OriginalSameActorLearningWork>,
        learning: LearningIterationRuntimeBootstrapV1,
        delivery: CircuitLearningDeliveryRuntimeV1,
        pending: PendingSuccessorOwner,
        checkpoint: OriginalLearningCheckpointRetirement,
    ) -> Result<Self, AgentdError> {
        let closing = CloseSameActorPhaseOnDrop::new(context.gate());
        OriginalSameActorRootContext::require_current(&context)?;
        work.require_identity_and_gate(context.identity(), context.gate())?;
        learning.require_identity(context.identity())?;
        OriginalLearningCheckpointRetirement::require_original_work(&checkpoint, &work)?;
        Ok(Self {
            context,
            work,
            checkpoint,
            learning,
            delivery,
            pending,
            _closing: closing,
        })
    }

    pub(crate) async fn run(
        self,
        store: AutomationStore,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        let work = Arc::clone(&self.work);
        let result = self.run_original_lanes(store, state, cancellation).await;
        work.gate().close();
        let joined = work.close_and_join_original_work().await;
        match (result, joined) {
            (Err(error), Err(join)) => Err(AgentdError::GenerationFenced(format!(
                "{error}; original learning cleanup: {join}"
            ))),
            (Err(error), Ok(())) => Err(error),
            (Ok(()), result) => result,
        }
    }

    async fn run_original_lanes(
        self,
        store: AutomationStore,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        OriginalSameActorRootContext::require_current(&self.context)?;
        self.work
            .require_identity_and_gate(state.identity(), self.context.gate())?;
        CircuitLearningDeliveryRuntimeV1::attach_sources(&self.delivery, &state)?;
        let stopped = cancellation.child_token();
        let learning = self.learning.run_original_same_actor(
            Arc::clone(&state),
            stopped.clone(),
            Arc::clone(&self.work),
        );
        let delivery = self
            .delivery
            .run(store.clone(), Arc::clone(&state), stopped.clone());
        let successor = self.pending.run(store, state, stopped.clone());
        tokio::pin!(learning, delivery, successor);
        let first = tokio::select! {
            result = &mut learning => FirstFinished::Learning(result),
            result = &mut delivery => FirstFinished::Delivery(result),
            result = &mut successor => FirstFinished::Successor(result),
            _ = cancellation.cancelled() => FirstFinished::Closed,
            _ = self.context.gate().cancelled() => FirstFinished::Closed,
            _ = tokio::time::sleep_until(tokio::time::Instant::from_std(
                self.context.gate().deadline().instant(),
            )) => FirstFinished::Closed,
        };
        // Do not abort or detach any owner. In particular the Pending C worker
        // joins CURRENT/FinalUse/source work already entered by its original lane.
        self.context.gate().close();
        stopped.cancel();
        let results = match first {
            FirstFinished::Learning(result) => {
                let (delivery, successor) = tokio::join!(delivery, successor);
                [
                    ("learning", result),
                    ("delivery", delivery),
                    ("successor", successor),
                ]
            }
            FirstFinished::Delivery(result) => {
                let (learning, successor) = tokio::join!(learning, successor);
                [
                    ("learning", learning),
                    ("delivery", result),
                    ("successor", successor),
                ]
            }
            FirstFinished::Successor(result) => {
                let (learning, delivery) = tokio::join!(learning, delivery);
                [
                    ("learning", learning),
                    ("delivery", delivery),
                    ("successor", result),
                ]
            }
            FirstFinished::Closed => {
                let (learning, delivery, successor) = tokio::join!(learning, delivery, successor);
                [
                    ("learning", learning),
                    ("delivery", delivery),
                    ("successor", successor),
                ]
            }
        };
        let failures: Vec<String> = results
            .into_iter()
            .filter_map(|(lane, result)| result.err().map(|error| format!("{lane}: {error}")))
            .collect();
        if failures.is_empty() {
            return Err(AgentdError::GenerationFenced(
                "original required learning lanes stopped".into(),
            ));
        }
        Err(AgentdError::GenerationFenced(failures.join("; ")))
    }
}

#[path = "same_actor_q24_phase_learning_worker_retirement.rs"]
mod retirement;
pub(crate) use retirement::OriginalRetiredLearningOwners;
pub(crate) use retirement::OriginalRetiredLearningPurposes;
pub(crate) use retirement::OriginalSameActorLearningPurposesRetired;
pub(crate) use retirement::OriginalSameActorLearningJoined;

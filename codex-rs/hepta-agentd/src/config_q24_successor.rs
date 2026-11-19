//! Both halves of the explicit waiting profile are installed together. The
//! normal Config/runtime AuthBus, Running and source-admission gates remain.

use super::*;
use crate::circuit_q24_successor::SuccessorSlot;
use crate::root_production_inputs::OriginalQ24SuccessorSession;

impl AgentdConfig {
    pub(crate) async fn with_original_pending_successor(
        mut self,
        session: std::sync::Arc<OriginalQ24SuccessorSession>,
        capacity: usize,
    ) -> Result<(Self, crate::OriginalQ24SuccessorHandoffV1), AgentdError> {
        self.require_no_circuit_task_profile()?;
        self.require_circuit_task_execution_profile()?;
        if !(1..=64).contains(&capacity) {
            return Err(AgentdError::Invalid(
                "successor capacity must be 1..64".into(),
            ));
        }
        let identity = self.identity.clone();
        let slot = SuccessorSlot::new_pending_slot();
        let learning = self.learning_iteration_bootstrap.as_mut().ok_or_else(|| {
            AgentdError::GenerationFenced(
                "assembled original Root learning bootstrap required".into(),
            )
        })?;
        let context = learning
            .prepare_original_successor_context(&identity, session, &slot)
            .await?;
        let (bootstrap, invocation, handoff) =
            crate::circuit_q24_successor::compose_original_successor_runtime(
                context, slot, capacity,
            )?;
        let config = self.with_circuit_task_bootstrap(bootstrap, invocation)?;
        Ok((config, handoff))
    }
}

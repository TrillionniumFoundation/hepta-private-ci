//! Drain observations for the original learning lane and its durable claims.
//! A pending claim is unresolved evidence, not proof that training is active.

use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use super::AgentdState;
use super::poisoned_state;
use crate::AgentdError;

#[derive(Default)]
pub(crate) struct LearningIterationActivityV1(AtomicUsize);

pub(crate) struct LearningIterationPendingV1(Arc<LearningIterationActivityV1>);

impl LearningIterationActivityV1 {
    pub(crate) fn admit(self: &Arc<Self>) -> LearningIterationPendingV1 {
        self.0.fetch_add(1, Ordering::AcqRel);
        LearningIterationPendingV1(Arc::clone(self))
    }

    pub(crate) fn pending_count(&self) -> usize {
        self.0.load(Ordering::Acquire)
    }
}

impl Drop for LearningIterationPendingV1 {
    fn drop(&mut self) {
        self.0.0.fetch_sub(1, Ordering::AcqRel);
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct LearningIterationDrainStatusV1 {
    pub(crate) queued_or_active: u32,
    pub(crate) unacknowledged_claims: u32,
}

impl LearningIterationDrainStatusV1 {
    pub(crate) fn is_clear(self) -> bool {
        self.queued_or_active == 0 && self.unacknowledged_claims == 0
    }

    pub(crate) fn blockers(self) -> Result<u32, AgentdError> {
        self.queued_or_active
            .checked_add(self.unacknowledged_claims)
            .ok_or_else(|| AgentdError::Protocol("learning drain blocker count overflow".into()))
    }
}

impl AgentdState {
    pub(crate) fn learning_iteration_pending_count(&self) -> usize {
        self.learning_iteration_activity
            .get()
            .map_or(0, |activity| activity.pending_count())
    }

    pub(crate) async fn learning_iteration_drain_status(
        &self,
    ) -> Result<LearningIterationDrainStatusV1, AgentdError> {
        // Keep the pre-snapshot activity sample: a worker may finish while the
        // database is being read. Never infer remote cancellation from a drop.
        let before = self.learning_iteration_pending_count();
        let store = self
            .automation
            .lock()
            .map_err(poisoned_state)?
            .clone()
            .ok_or_else(|| AgentdError::Protocol("learning drain owner is unavailable".into()))?;
        let unacknowledged_claims =
            store
                .circuit_learning_drain_blockers()
                .await
                .map_err(|error| {
                    AgentdError::Protocol(format!("learning drain history unavailable: {error:?}"))
                })?;
        let queued_or_active =
            u32::try_from(before.max(self.learning_iteration_pending_count()))
                .map_err(|_| AgentdError::Protocol("learning pending count exceeds u32".into()))?;
        Ok(LearningIterationDrainStatusV1 {
            queued_or_active,
            unacknowledged_claims,
        })
    }
}

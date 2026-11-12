//! Purpose retirement of the actual joined Learning aggregate. This never
//! enters the ordinary owner lane or samples new Current after Session pause.

use super::*;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::same_actor_q24_deployment::OriginalRootRetirementIntent;

impl OriginalCellQ24LearningStageOwnersV1 {
    pub(crate) fn retire_original_model_purpose(
        &self,
        intent: &OriginalRootRetirementIntent,
        identity: &AgentdIdentity,
        work: &Arc<OriginalSameActorLearningWork>,
    ) -> Result<(), AgentdError> {
        let mut closing = work.original_failure_scope();
        work.require_original_retirement_identity(identity, work.gate())?;
        intent.require_original_origin(identity, work.gate())?;
        let original = self.inner.same_actor_work.as_ref()
            .ok_or_else(|| refused("aggregate has no original phase Work"))?;
        if !Arc::ptr_eq(original, work) || self.inner.cancelled.load(Ordering::Acquire) {
            return Err(refused("aggregate retirement is foreign or already cancelled"));
        }
        // The real semaphore and the real owner mutex exclude a stage effect,
        // including a started blocking closure. Neither a count nor a token
        // supplied by the caller stands in for these actual owner locks.
        let _lane = self.inner.lane.try_acquire()
            .map_err(|_| refused("aggregate retirement lane is busy or closed"))?;
        let mut owners = self.inner.owners.try_lock()
            .map_err(|_| refused("aggregate retirement owner is busy or poisoned"))?;
        intent.require_original_origin(identity, work.gate())?;
        if self.inner.cancelled.load(Ordering::Acquire) {
            return Err(refused("aggregate was cancelled before Model retirement"));
        }
        // This stops future ordinary aggregate entry without closing the
        // common Gate or releasing the real Model/file/receipt owners.
        self.inner.lane.close();
        AgentdRootQ24ModelFactoryV1::retire_original_model_after_root_intent(
            &mut owners.factory, intent, identity, work.gate(),
        )?;
        intent.require_original_origin(identity, work.gate())?;
        drop(owners);
        closing.disarm();
        Ok(())
    }
}

fn refused(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::GenerationFenced(error.to_string())
}

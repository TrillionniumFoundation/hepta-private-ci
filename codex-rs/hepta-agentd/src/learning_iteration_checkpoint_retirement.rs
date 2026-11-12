//! Retain the same actual checkpoint client across the Learning worker join.
//! The close-only handle is made only while that client enters its concrete
//! phase ports. It cannot be deserialized or built from a receipt or digest.

use std::sync::Arc;

use super::*;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::same_actor_q24_deployment::OriginalRootRetirementIntent;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
use crate::same_actor_q24_phase_learning::OriginalSameActorLearningWork;

pub(crate) struct OriginalLearningCheckpointRetirement {
    _closing: CloseSameActorPhaseOnDrop,
    client: Arc<AgentdLearningCheckpointClientV1>,
    identity: AgentdIdentity,
    work: Arc<OriginalSameActorLearningWork>,
}

impl AgentdLearningCheckpointClientV1 {
    // This private admission only borrows the real populated channel. It
    // grants no retirement authority: the sole production caller first
    // validates the actual Intent, then holds this guard through shutdown.
    pub(super) fn lock_original_retirement_channel(
        &self,
    ) -> Result<std::sync::MutexGuard<'_, Option<Channel>>, AgentdError> {
        let held = self
            .channel
            .try_lock()
            .map_err(|_| refused("checkpoint retirement is busy or poisoned"))?;
        if held.is_none() {
            return Err(refused("checkpoint retirement has an uncertain exchange"));
        }
        Ok(held)
    }

    pub(crate) fn into_original_retirable_checkpoint(
        self,
        identity: &AgentdIdentity,
        work: &Arc<OriginalSameActorLearningWork>,
    ) -> Result<(Arc<Self>, OriginalLearningCheckpointRetirement), AgentdError> {
        let closing = work.original_failure_scope();
        work.require_original_retirement_identity(identity, work.gate())?;
        let phase = self.phase.as_ref().ok_or_else(|| {
            refused("retirable checkpoint requires its actual phase channel")
        })?;
        if !Arc::ptr_eq(phase.gate(), work.gate()) {
            return Err(refused("checkpoint and Work have different original Gates"));
        }
        phase.require_open()?;
        work.require_original_delivery_request(&self.initial.request, &self.initial.owners)?;
        if self.scope.is_none() {
            return Err(refused("retirable checkpoint requires the original frozen scope"));
        }
        let client = Arc::new(self);
        let retirement = OriginalLearningCheckpointRetirement {
            _closing: closing,
            client: Arc::clone(&client),
            identity: identity.clone(),
            work: Arc::clone(work),
        };
        Ok((client, retirement))
    }
}

impl OriginalLearningCheckpointRetirement {
    pub(crate) fn require_original_work(
        &self,
        work: &Arc<OriginalSameActorLearningWork>,
    ) -> Result<(), AgentdError> {
        if !Arc::ptr_eq(&self.work, work) {
            self.work.gate().close();
            work.gate().close();
            return Err(refused("checkpoint retirement has another original Work"));
        }
        work.require_original_retirement_identity(&self.identity, work.gate())
    }

    pub(crate) fn retire_original_checkpoint_after_root_intent(
        &self,
        intent: &OriginalRootRetirementIntent,
    ) -> Result<(), AgentdError> {
        let mut closing = self.work.original_failure_scope();
        self.require_original_work(&self.work)?;
        intent.require_original_origin(&self.identity, self.work.gate())?;
        let phase = self.client.phase.as_ref().ok_or_else(|| {
            refused("retirable checkpoint lost its original required channel")
        })?;
        if !Arc::ptr_eq(phase.gate(), self.work.gate()) {
            return Err(refused("checkpoint retirement phase differs"));
        }
        // The original client leaves this whole slot empty through framing
        // and semantic validation. A competing or failed exchange is refused,
        // never converted to a normal EOF. Keep the same slot held throughout
        // the actual socket shutdown; do not drop its transport or guard.
        let held = AgentdLearningCheckpointClientV1::lock_original_retirement_channel(
            &self.client,
        )?;
        let channel = held.as_ref()
            .ok_or_else(|| refused("checkpoint retirement has an uncertain exchange"))?;
        let root = RootObservationStream::root_lifetime(&channel.transport);
        crate::root_observation_stream::check_lifetime(root.get_ref())
            .map_err(refused)?;
        phase.shutdown_original_after_root_intent(intent)?;
        crate::root_observation_stream::check_lifetime(root.get_ref())
            .map_err(refused)?;
        intent.require_original_origin(&self.identity, self.work.gate())?;
        // RequiredSameActorPhaseChannel retains its alias and armed guard.
        // Its one-way retired state rejects every subsequent business call.
        drop(held);
        closing.disarm();
        Ok(())
    }
}

fn refused(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::GenerationFenced(error.to_string())
}

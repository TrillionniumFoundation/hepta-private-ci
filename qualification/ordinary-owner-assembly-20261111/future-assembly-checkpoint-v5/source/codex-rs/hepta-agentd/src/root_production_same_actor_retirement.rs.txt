//! Retire only the four actual non-observation Root purposes retained by the
//! sealed receiver. Session and late Learning/Model/Publication have their own
//! actual joined owners; neither an empty count nor public data replaces them.

use super::*;

impl OriginalSameActorRootContext {
    /// The original watcher holds only Gate, not Context or Tokio tasks.
    /// Take the real handle once, release this mutex, then join it explicitly.
    pub(crate) fn finish_original_deadline_watch(
        &self,
        exited: &crate::same_actor_q24_deployment::OriginalRootProcessExited,
    ) -> Result<(), AgentdError> {
        exited.require_original_cleanup_origin(&self.identity, &self.gate)?;
        let watch = {
            self._deadline_watch.lock()
                .map_err(|_| refused("actual deadline watcher custody is poisoned"))?
                .take().ok_or_else(|| refused("actual deadline watcher was already taken"))?
        };
        watch.finish_original_after_root_exit(exited, &self.identity)
    }

    pub(crate) fn retire_original_runtime_purposes(
        &self,
        intent: &crate::same_actor_q24_deployment::OriginalRootRetirementIntent,
    ) -> Result<(), AgentdError> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        intent.require_original_origin(&self.identity, &self.gate)?;
        // This is the same Arc returned by the actual ReadHead constructor,
        // before its protected inputs moved into the ordinary Runtime.
        AgentdUnixCognitiveCheckpointTransport::retire_original_root_checkpoint_purpose(
            self.checkpoint_transport.as_ref(), intent,
        )?;
        AgentdUnixFinalUseGrantProvider::retire_original_root_grant_purpose(
            self.grants.as_ref(), intent,
        )?;
        // Both references came from the exact required objects moved into the
        // original consumer frontier closures. Their real jobs and consumer
        // barriers have already joined before the four-cap Intent exists.
        OriginalRequiredPurposeRetirement::shutdown_original_after_root_intent(
            &self.device_retirement, intent,
        )?;
        OriginalRequiredPurposeRetirement::shutdown_original_after_root_intent(
            &self.notes_retirement, intent,
        )?;
        intent.require_original_origin(&self.identity, &self.gate)?;
        closing.disarm();
        Ok(())
    }
}

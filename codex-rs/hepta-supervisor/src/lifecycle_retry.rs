//! Retry original release intents after temporary Fleet entry contention.

use super::*;

impl<D: ProcessDriver> Supervisor<D> {
    pub(crate) fn retain_start_failure(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        generation: u64,
        error: SupervisorError,
    ) -> Result<(), SupervisorError> {
        slot.deferred_start_failure = Some(crate::runtime::DeferredStartFailure {
            generation,
            error,
        });
        let error = self.retry_start_failure_cleanup(agent_id, slot)?.ok_or_else(|| {
            SupervisorError::Invalid("start failure cleanup lost its original failure".to_owned())
        })?;
        Err(error)
    }

    pub(crate) fn retry_start_failure_cleanup(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<Option<SupervisorError>, SupervisorError> {
        let Some(failure) = slot.deferred_start_failure.as_ref() else {
            return Ok(None);
        };
        let generation = failure.generation;
        // Only the original Failed publication is retried. Lease publication
        // failure already took its one original kill path; this witness is
        // neither a process handle nor evidence that the child exited.
        self.transition_without_runtime(agent_id, slot, generation, AgentLifecycle::Failed)?;
        Ok(slot.deferred_start_failure.take().map(|failure| failure.error))
    }

    pub(crate) fn retry_unstarted_release(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        if let Some(error) = self.retry_start_failure_cleanup(agent_id, slot)? {
            let completion = match slot.release_change.as_ref().map(|change| change.phase) {
                Some(ReleaseChangePhase::TargetStarting) => {
                    self.start_automatic_rollback(agent_id, slot, now).map(|_| ())
                }
                Some(ReleaseChangePhase::AutomaticRollbackStarting) => {
                    self.finish_failed_rollback(agent_id, slot)
                }
                Some(ReleaseChangePhase::WaitingForTargetExit) | None => {
                    Err(SupervisorError::Invalid("failed start lost its release phase".to_owned()))
                }
            };
            // Report the original start failure once even when the next
            // already-owned rollback is temporarily blocked on Fleet entry.
            return match completion {
                Err(next) if !next.is_lifecycle_busy() => Err(SupervisorError::Invalid(format!(
                    "{error}; release recovery failed: {next}"
                ))),
                Ok(()) | Err(_) => Err(error),
            };
        }
        let Some(change) = slot.release_change.as_ref() else {
            return Ok(());
        };
        match change.phase {
            ReleaseChangePhase::WaitingForTargetExit => {
                self.continue_release_change_after_exit(agent_id, slot, now)?;
            }
            ReleaseChangePhase::TargetStarting => {
                // No runtime exists: a previous try-lock returned Busy before
                // spawn. This is not an observed failed target process.
                let target = match self.refresh_release_for_transition(agent_id, &change.target) {
                    Ok(target) => target,
                    Err(_) => {
                        self.start_automatic_rollback(agent_id, slot, now)?;
                        return Ok(());
                    }
                };
                if self.verify_release_binding_against_transaction(agent_id, slot, &target, /*target*/ true).is_err() {
                    self.start_automatic_rollback(agent_id, slot, now)?;
                    return Ok(());
                }
                match self.start_release_slot(agent_id, slot, target, now) {
                    Ok(()) => {}
                    Err(error) if error.is_lifecycle_busy() || slot.deferred_start_failure.is_some() => return Err(error),
                    Err(_) => { self.start_automatic_rollback(agent_id, slot, now)?; }
                }
            }
            ReleaseChangePhase::AutomaticRollbackStarting => {
                // Queue and journal publication happened once when this phase
                // was prepared. Revalidate its original source at final use,
                // then retry only the process start that never happened.
                let rollback = match self.refresh_release_for_transition(agent_id, &change.origin) {
                    Ok(rollback) => rollback,
                    Err(error) => {
                        let _ = self.enter_unsigned_release_recovery(agent_id, slot);
                        return Err(error);
                    }
                };
                if let Err(error) = self.verify_release_binding_against_transaction(
                    agent_id, slot, &rollback, /*target*/ false,
                ) {
                    let _ = self.enter_unsigned_release_recovery(agent_id, slot);
                    return Err(error);
                }
                self.start_prepared_rollback(agent_id, slot, rollback, now)?;
            }
        }
        Ok(())
    }
}

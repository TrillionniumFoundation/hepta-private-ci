//! Final Session field retirement after the actual Root-exit observation.
//! The real paused-purpose cap is consumed, every already observed handle is
//! rechecked, and the original writer File is released only after all owners.

use super::*;
use crate::same_actor_q24_deployment::OriginalRootProcessExited;

/// No public constructor or Clone. The exact original Session fields and
/// sole retained writer File have actually been dropped before this returns.
/// This is local resource evidence, never authority or daemon OS-exit proof.
pub(crate) struct OriginalRootSessionFullyRetired {
    identity: AgentdIdentity,
    gate: Arc<SameActorPhaseGate>,
    consumers: OriginalConsumerJoinSummary,
}

impl OriginalRootSessionCustodySlot {
    /// Called after the actual Runtime/Learning/C/coordinator/Context owners
    /// have been released. The supplied real observation-purpose cap is the
    /// last expected extra Session-resource custodian, not decoded status.
    pub(crate) fn finish_original_retired_session_after_root_exit(
        &self,
        retired: OriginalRootSessionObservationRetired,
        exited: &OriginalRootProcessExited,
    ) -> Result<OriginalRootSessionFullyRetired, AgentdError> {
        OriginalRootProcessExited::require_original_cleanup_origin(
            exited,
            &retired.original.identity,
            &retired.original.original.gate,
        )?;
        let finished = self.finish_original_retired_fields(retired)?;
        OriginalRootSessionFullyRetired::require_original_cleanup_origin(
            &finished, &finished.identity, &finished.gate, exited,
        )?;
        Ok(finished)
    }

    fn finish_original_retired_fields(
        &self,
        retired: OriginalRootSessionObservationRetired,
    ) -> Result<OriginalRootSessionFullyRetired, AgentdError> {
        let identity = retired.original.identity.clone();
        let gate = Arc::clone(&retired.original.original.gate);
        let summary = retired.original.consumers;
        let mut state = self.state.lock().map_err(join_error)?;
        if state.stopped {
            return Err(join_error("fault-stopped Session cannot become normal retirement"));
        }
        let original = state.original.as_ref()
            .ok_or_else(|| join_error("actual Session custody was never registered or consumed"))?;
        if !Arc::ptr_eq(original, &retired.original.original)
            || !original.session_retired.load(Ordering::Acquire)
            || retired.original.resources._stream.is_some()
            || retired.original.resources._stop.is_some()
            || retired.original.resources.live.active.load(Ordering::Acquire)
            || !Arc::ptr_eq(&original._writer_file, &retired.original.resources._writer_file)
            || !original.pause.requested()
        {
            return Err(join_error("actual Session fields or observation purpose remain live"));
        }
        if !retired.original.resources.live.proof.matches_registered_process(
            &identity.agent_id, identity.spawn_generation,
        ) || !retired.original.resources.live.phase.as_ref()
            .is_some_and(|phase| Arc::ptr_eq(phase, &gate))
        {
            return Err(join_error("retired Session has a different original process or Gate"));
        }
        {
            let worker = original.worker.try_lock().map_err(join_error)?;
            if worker.handle.is_some()
                || worker.observed != Some(OriginalRootWorkerTermination::Returned)
            {
                return Err(join_error("original Session worker has no normal observed join"));
            }
        }
        OriginalConsumerJobs::require_original_joined_summary(&original.consumers, &summary)
            .map_err(join_error)?;
        {
            let paused = original.pause.state.lock().map_err(join_error)?;
            if !matches!(*paused, OriginalPauseState::Taken) {
                return Err(join_error("original observation resources are still parked"));
            }
        }

        // All real joins and the Session's final-field notification were
        // checked above. Drop the exact parked resources and failure guards,
        // including their File share, before taking the last custody below.
        // The Slot mutex prevents any concurrent cleanup from taking a new
        // strong custody share during this synchronous transition.
        drop(retired);
        {
            let original = Arc::get_mut(state.original.as_mut()
                .ok_or_else(|| join_error("original Session custody disappeared"))?)
                .ok_or_else(|| join_error("another actual Session custodian is still held"))?;
            let writer = Arc::get_mut(&mut original._writer_file)
                .ok_or_else(|| join_error("another original writer custody share is still held"))?;
            let file = writer.get_mut()
                .ok_or_else(|| join_error("original writer File was never retained"))?;
            // Exclusive access checks a real retained object, not a count
            // used as a replacement for task completion. Any extra strong or
            // weak File owner conservatively refuses this normal result.
            Arc::get_mut(file)
                .ok_or_else(|| join_error("another owner of the original writer File remains"))?;
        }
        let original = state.original.take()
            .ok_or_else(|| join_error("original Session custody cannot be consumed twice"))?;
        state.stopped = true;
        drop(state);
        // Its original Drop requests fault closure only after real Root exit;
        // every actual task was already joined. The original field order
        // drops worker/consumers/pause before its last writer File field.
        drop(original);
        Ok(OriginalRootSessionFullyRetired { identity, gate, consumers: summary })
    }

    /// Exercise the same actual fields/File transition in same-UID component
    /// tests, without fabricating Root-exit or business capabilities.
    #[cfg(test)]
    pub(in super::super::super) fn component_finish_original_retired_session(
        &self,
        retired: OriginalRootSessionObservationRetired,
    ) -> Result<OriginalRootSessionFullyRetired, AgentdError> {
        self.finish_original_retired_fields(retired)
    }
}

impl OriginalRootSessionFullyRetired {
    pub(crate) fn require_original_cleanup_origin(
        &self,
        identity: &AgentdIdentity,
        gate: &Arc<SameActorPhaseGate>,
        exited: &OriginalRootProcessExited,
    ) -> Result<(), AgentdError> {
        if &self.identity != identity || !Arc::ptr_eq(&self.gate, gate)
            || self.consumers.registered != self.consumers.joined
            || self.consumers.first_observed_failure.is_some()
            || self.consumers.admission_poisoned
        {
            self.gate.close();
            return Err(join_error("actual final Session cleanup origin differs"));
        }
        OriginalRootProcessExited::require_original_cleanup_origin(exited, identity, gate)
    }
}

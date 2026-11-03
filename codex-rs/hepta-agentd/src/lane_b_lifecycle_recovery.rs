//! Read-only coordinator projection of the original journal's stop decisions.
//! This preserves terminal/cancellation revisions and never admits a run.

use super::*;
use codex_hepta_learning_ledger::{RunCancellationRecordV1, RunClosedPhaseV1, RunClosedRecordV1};

impl AgentRunCoordinator {
    pub(crate) fn restore_original_observation(&mut self, mut recovery: RunRecovery,
        cancellation: Option<&RunCancellationRecordV1>, closed: Option<&RunClosedRecordV1>) -> Result<RunReceipt, AgentRunError> {
        validate_recovery(&recovery)?;
        let run_id = recovery.snapshot.run_id.clone();
        if cancellation.is_some_and(|fact| fact.run_id.as_str() != run_id.as_str())
            || closed.is_some_and(|fact| fact.run_id.as_str() != run_id.as_str())
        {
            return Err(AgentRunError::MixedSnapshot);
        }
        if let Some(current) = self.runs.get(&run_id) {
            if current.snapshot != recovery.snapshot
                || current.context_digest.as_deref() != Some(recovery.context_digest.as_str())
                || current.compilation_receipt_digest.as_deref() != Some(recovery.compilation_receipt_digest.as_str())
            {
                return Err(AgentRunError::MixedSnapshot);
            }
            if closed.is_none() && cancellation.is_none() {
                // An immutable older anchor may observe a later cancellation,
                // but cannot borrow a revision the original owner has not
                // reached or contradict a cancellation already in that anchor.
                if current.revision < recovery.revision {
                    return Err(AgentRunError::StaleRevision);
                }
                if (current.revision == recovery.revision || recovery.cancel_reason.is_some())
                    && current.cancel_reason != recovery.cancel_reason
                {
                    return Err(AgentRunError::Conflict);
                }
                if matches!(current.phase, RunPhase::Indeterminate | RunPhase::Cancelling) {
                    return Ok(receipt(current, /*idempotent*/ true));
                }
                return Err(AgentRunError::InvalidTransition);
            }
        }
        if let Some(closed) = closed {
            if closed.closed_revision < recovery.revision {
                return Err(AgentRunError::StaleRevision);
            }
            let phase = match closed.phase {
                RunClosedPhaseV1::Cancelled => RunPhase::Cancelled,
                RunClosedPhaseV1::Succeeded => RunPhase::Succeeded,
                RunClosedPhaseV1::Failed => RunPhase::Failed,
            };
            if let Some(current) = self.runs.get(&run_id) {
                if current.revision > closed.closed_revision
                    || (current.revision == closed.closed_revision
                        && (current.phase != phase || current.cancel_reason != closed.cancel_reason))
                {
                    return Err(AgentRunError::Conflict);
                }
            }
            recovery.revision = closed.closed_revision;
            recovery.cancel_reason = closed.cancel_reason.clone();
            if !self.runs.contains_key(&run_id) { self.recover_indeterminate(recovery)?; }
            let current = self.runs.get_mut(&run_id).ok_or(AgentRunError::RunNotFound)?;
            current.revision = closed.closed_revision;
            current.phase = phase;
            current.cancel_reason = closed.cancel_reason.clone();
            current.cancel_ack_deadline_ms = None;
            return Ok(receipt(current, /*idempotent*/ true));
        }
        if let Some(cancelled) = cancellation {
            if cancelled.revision < recovery.revision { return Err(AgentRunError::StaleRevision); }
            if let Some(current) = self.runs.get(&run_id)
                && current.revision >= cancelled.revision {
                if current.cancel_reason.as_deref() != Some(cancelled.cancel_reason.as_str())
                    || matches!(current.phase, RunPhase::Admitted | RunPhase::ContextAttached | RunPhase::Dispatched) {
                    return Err(AgentRunError::Conflict);
                }
                return Ok(receipt(current, /*idempotent*/ true));
            }
            recovery.revision = cancelled.revision;
            recovery.cancel_reason = Some(cancelled.cancel_reason.clone());
            if !self.runs.contains_key(&run_id) { return self.recover_indeterminate(recovery); }
            let current = self.runs.get_mut(&run_id).ok_or(AgentRunError::RunNotFound)?;
            current.revision = cancelled.revision;
            current.phase = RunPhase::Indeterminate;
            current.cancel_reason = Some(cancelled.cancel_reason.clone());
            current.cancel_ack_deadline_ms = None;
            return Ok(receipt(current, /*idempotent*/ true));
        }
        self.recover_indeterminate(recovery)
    }
}

#[cfg(test)]
#[path = "lane_b_lifecycle_recovery_tests.rs"]
mod tests;

//! Original run lifecycle decisions remain in the original Objective journal.
//! The journal lock precedes runtime/runs locks; no guard crosses an await.

use super::*;
use codex_hepta_learning_ledger::{RunCancellationRecordV1, RunClosedPhaseV1, RunClosedRecordV1};

pub(super) fn lifecycle_error(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Protocol(format!("original run journal lifecycle: {error}"))
}

pub(crate) fn require_fresh(journal: Option<&DurableRunStartJournal>, run_id: &str) -> Result<(), AgentdError> {
    let Some(journal) = journal else { return Ok(()); };
    let run_id = StableId::new(run_id).map_err(lifecycle_error)?;
    if journal.cancellation(&run_id).map_err(lifecycle_error)?.is_some()
        || journal.closed(&run_id).map_err(lifecycle_error)?.is_some()
    {
        return Err(AgentdError::GenerationFenced(
            "original run is cancelled or closed; recovery is observation-only".to_owned(),
        ));
    }
    Ok(())
}

/// Persist the actual reducer receipt, never the caller's proposed reason or
/// outcome. Technical Indeterminate without cancellation remains recoverable.
pub(super) fn persist(journal: Option<&mut DurableRunStartJournal>, receipt: &RunReceipt) -> Result<(), AgentdError> {
    let Some(journal) = journal else { return Ok(()); };
    let run_id = StableId::new(&receipt.run_id).map_err(lifecycle_error)?;
    let Some(start_digest) = journal.run_start_record_digest(&run_id).map_err(lifecycle_error)? else {
        return Ok(());
    };
    let closed_phase = match receipt.phase {
        crate::RunPhase::Cancelled => Some(RunClosedPhaseV1::Cancelled),
        crate::RunPhase::Succeeded => Some(RunClosedPhaseV1::Succeeded),
        crate::RunPhase::Failed => Some(RunClosedPhaseV1::Failed),
        crate::RunPhase::Admitted | crate::RunPhase::ContextAttached | crate::RunPhase::Dispatched
        | crate::RunPhase::Cancelling | crate::RunPhase::Indeterminate => None,
    };
    if let Some(phase) = closed_phase {
        let record = RunClosedRecordV1 {
            run_id, run_start_record_digest: start_digest, closed_revision: receipt.revision,
            phase, cancel_reason: receipt.cancel_reason.clone(),
        };
        journal.append_closed(journal.head_digest(), record).map_err(lifecycle_error)?;
    } else if let Some(reason) = receipt.cancel_reason.as_ref() {
        if let Some(original) = journal.cancellation(&run_id).map_err(lifecycle_error)? {
            if original.run_start_record_digest != start_digest || original.cancel_reason != *reason
                || original.revision > receipt.revision
            {
                return Err(lifecycle_error("cancellation differs from the original accepted decision"));
            }
        } else {
            let record = RunCancellationRecordV1 {
                run_id, run_start_record_digest: start_digest, revision: receipt.revision,
                cancel_reason: reason.clone(),
            };
            journal.append_cancellation(journal.head_digest(), record).map_err(lifecycle_error)?;
        }
    }
    Ok(())
}

impl AgentdState {
    /// Serialize against this state's installed original journal. Passing no
    /// journal preserves ordinary non-Objective coordinator compatibility.
    pub(crate) fn with_original_run_journal<T>(&self,
        action: impl FnOnce(Option<&mut DurableRunStartJournal>) -> Result<T, AgentdError>) -> Result<T, AgentdError> {
        match self.objective_runtime.get() {
            Some(host) => host.with_run_journal(|journal| action(Some(journal))),
            None => action(None),
        }
    }

    pub(crate) fn with_fresh_original_run<T>(&self, run_id: &str,
        action: impl FnOnce() -> Result<T, AgentdError>) -> Result<T, AgentdError> {
        self.with_original_run_journal(|journal| {
            require_fresh(journal.as_deref(), run_id)?;
            action()
        })
    }

    pub(crate) fn native_continuation_allowed(&self, run_id: &str) -> Result<bool, AgentdError> {
        self.with_original_run_journal(|journal| {
            let Some(journal) = journal else { return Ok(true); };
            let run_id = StableId::new(run_id).map_err(lifecycle_error)?;
            Ok(journal.cancellation(&run_id).map_err(lifecycle_error)?.is_none()
                && journal.closed(&run_id).map_err(lifecycle_error)?.is_none())
        })
    }

    pub(super) fn cancel_original_run(&self, now_ms: u64, run_id: &str, expected_revision: u64,
        reason: &str) -> Result<(crate::CancellationDisposition, RunReceipt), AgentdError> {
        self.with_original_run_journal(|journal| {
            let mut runs = self.runs.lock().map_err(poisoned_state)?;
            let result = runs.cancel_run(now_ms, run_id, expected_revision, reason).map_err(run_error)?;
            // Failure is not acknowledged. Retain the stricter in-memory
            // decision; never reopen admission because persistence failed.
            persist(journal, &result.1)?;
            Ok(result)
        })
    }

    pub(super) fn observe_original_run(&self, run_id: &str, expected_revision: u64,
        phase: crate::RunPhase, terminal_observed: bool) -> Result<RunReceipt, AgentdError> {
        self.with_original_run_journal(|journal| {
            let mut runs = self.runs.lock().map_err(poisoned_state)?;
            let receipt = runs.observe_terminal(run_id, expected_revision, phase, terminal_observed).map_err(run_error)?;
            persist(journal, &receipt)?;
            Ok(receipt)
        })
    }

    pub(super) fn release_original_run(&self, run_id: &str, expected_revision: u64) -> Result<RunReceipt, AgentdError> {
        self.with_original_run_journal(|journal| {
            let mut runs = self.runs.lock().map_err(poisoned_state)?;
            let receipt = runs.run(run_id).ok_or_else(|| run_error(crate::AgentRunError::RunNotFound))?;
            if receipt.revision != expected_revision { return Err(run_error(crate::AgentRunError::StaleRevision)); }
            if !matches!(receipt.phase, crate::RunPhase::Cancelled | crate::RunPhase::Succeeded | crate::RunPhase::Failed) {
                return Err(run_error(crate::AgentRunError::InvalidTransition));
            }
            // The original terminal fact must be durable before its sole
            // runtime projection is removed, including a lost release ACK.
            persist(journal, &receipt)?;
            runs.remove_closed_run(run_id, expected_revision).map_err(run_error)
        })
    }
}

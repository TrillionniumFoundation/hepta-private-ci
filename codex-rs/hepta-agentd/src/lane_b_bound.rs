//! Atomic immutable admission checks for worker lifecycle mutations.

use super::AgentRunCoordinator;
use super::AgentRunError;
use super::CancellationDisposition;
use super::RunPhase;
use super::RunReceipt;
use super::RunSnapshot;
use super::receipt;
use super::require_revision;

impl AgentRunCoordinator {
    pub(crate) fn mark_bound_dispatched(
        &mut self,
        now_ms: u64,
        snapshot: &RunSnapshot,
        expected_revision: u64,
        context_digest: &str,
        compilation_receipt_digest: &str,
    ) -> Result<RunReceipt, AgentRunError> {
        self.require_bound_run(
            snapshot,
            expected_revision,
            context_digest,
            compilation_receipt_digest,
        )?;
        self.mark_dispatched(now_ms, &snapshot.run_id, expected_revision)
    }

    pub(crate) fn cancel_bound_run(
        &mut self,
        now_ms: u64,
        snapshot: &RunSnapshot,
        expected_revision: u64,
        context_digest: &str,
        compilation_receipt_digest: &str,
        reason: &str,
    ) -> Result<(CancellationDisposition, RunReceipt), AgentRunError> {
        self.require_bound_run(
            snapshot,
            expected_revision,
            context_digest,
            compilation_receipt_digest,
        )?;
        self.cancel_run(now_ms, &snapshot.run_id, expected_revision, reason)
    }

    pub(crate) fn observe_bound_terminal(
        &mut self,
        snapshot: &RunSnapshot,
        expected_revision: u64,
        context_digest: &str,
        compilation_receipt_digest: &str,
        phase: RunPhase,
        terminal_observed: bool,
    ) -> Result<RunReceipt, AgentRunError> {
        self.require_bound_run(
            snapshot,
            expected_revision,
            context_digest,
            compilation_receipt_digest,
        )?;
        self.observe_terminal(
            &snapshot.run_id,
            expected_revision,
            phase,
            terminal_observed,
        )
    }

    fn require_bound_run(
        &self,
        snapshot: &RunSnapshot,
        expected_revision: u64,
        context_digest: &str,
        compilation_receipt_digest: &str,
    ) -> Result<(), AgentRunError> {
        let record = self
            .runs
            .get(&snapshot.run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        // Run IDs and revisions can recur after closed-record removal. Bind
        // the complete immutable admission before even an idempotent return.
        if record.snapshot != *snapshot
            || record.context_digest.as_deref() != Some(context_digest)
            || record.compilation_receipt_digest.as_deref() != Some(compilation_receipt_digest)
        {
            return Err(AgentRunError::MixedSnapshot);
        }
        require_revision(record, expected_revision)
    }

    pub(crate) fn run_reconciliation_state(
        &self,
        run_id: &str,
    ) -> Option<(RunSnapshot, RunReceipt)> {
        let record = self.runs.get(run_id)?;
        Some((
            record.snapshot.clone(),
            receipt(record, /*idempotent*/ false),
        ))
    }
}

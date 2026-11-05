//! Exact admission reads and atomic bound lifecycle mutations for physical workers.

use crate::AgentdError;
use crate::AgentdPayload;

use super::AgentdState;
use super::internal_run_phase;
use super::internal_run_snapshot;
use super::now_ms;
use super::poisoned_state;
use super::require_current_run_identity;
use super::require_run_admission_ready;
use super::require_run_reconciliation_ready;
use super::run_error;
use super::wire_cancellation_disposition;
use super::wire_run_receipt;

impl AgentdState {
    pub(super) fn run_mark_bound_dispatched_payload(
        &self,
        binding: crate::AgentRunBinding,
    ) -> Result<AgentdPayload, AgentdError> {
        {
            let runtime = self.runtime.lock().map_err(poisoned_state)?;
            require_run_admission_ready(
                runtime.lifecycle,
                runtime.app_server_ready,
                runtime.fenced,
            )?;
            require_current_run_identity(
                &self.identity,
                runtime.current_generation,
                binding.snapshot.generation,
                &binding.snapshot.fence_digest,
            )?;
        }
        let snapshot = internal_run_snapshot(binding.snapshot);
        let receipt = self
            .runs
            .lock()
            .map_err(poisoned_state)?
            .mark_bound_dispatched(
                now_ms()?,
                &snapshot,
                binding.expected_revision,
                &binding.context_digest,
                &binding.compilation_receipt_digest,
            )
            .map_err(run_error)?;
        Ok(AgentdPayload::RunReceipt(wire_run_receipt(receipt)))
    }

    pub(super) fn run_cancel_bound_payload(
        &self,
        binding: crate::AgentRunBinding,
        reason: String,
    ) -> Result<AgentdPayload, AgentdError> {
        {
            let runtime = self.runtime.lock().map_err(poisoned_state)?;
            require_run_reconciliation_ready(runtime.lifecycle, runtime.fenced)?;
        }
        let snapshot = internal_run_snapshot(binding.snapshot);
        let (disposition, receipt) = self
            .runs
            .lock()
            .map_err(poisoned_state)?
            .cancel_bound_run(
                now_ms()?,
                &snapshot,
                binding.expected_revision,
                &binding.context_digest,
                &binding.compilation_receipt_digest,
                &reason,
            )
            .map_err(run_error)?;
        Ok(AgentdPayload::RunCancellation(
            crate::AgentRunCancellation {
                disposition: wire_cancellation_disposition(disposition),
                receipt: wire_run_receipt(receipt),
            },
        ))
    }

    pub(super) fn run_observe_bound_terminal_payload(
        &self,
        observation: crate::AgentRunTerminalObservation,
    ) -> Result<AgentdPayload, AgentdError> {
        {
            let runtime = self.runtime.lock().map_err(poisoned_state)?;
            require_run_reconciliation_ready(runtime.lifecycle, runtime.fenced)?;
        }
        let binding = observation.binding;
        let snapshot = internal_run_snapshot(binding.snapshot);
        let receipt = self
            .runs
            .lock()
            .map_err(poisoned_state)?
            .observe_bound_terminal(
                &snapshot,
                binding.expected_revision,
                &binding.context_digest,
                &binding.compilation_receipt_digest,
                internal_run_phase(observation.phase),
                observation.terminal_observed,
            )
            .map_err(run_error)?;
        Ok(AgentdPayload::RunReceipt(wire_run_receipt(receipt)))
    }

    pub(super) fn run_reconciliation_state_payload(
        &self,
        run_id: String,
    ) -> Result<AgentdPayload, AgentdError> {
        {
            let runtime = self.runtime.lock().map_err(poisoned_state)?;
            require_run_reconciliation_ready(runtime.lifecycle, runtime.fenced)?;
        }
        let run = self
            .runs
            .lock()
            .map_err(poisoned_state)?
            .run_reconciliation_state(&run_id)
            .map(|(snapshot, receipt)| crate::AgentRunReconciliationState {
                snapshot: crate::AgentRunSnapshot {
                    run_id: snapshot.run_id,
                    request_digest: snapshot.request_digest,
                    objective_digest: snapshot.objective_digest,
                    body_digest: snapshot.body_digest,
                    artifact_set_digest: snapshot.artifact_set_digest,
                    authority_epoch: snapshot.authority_epoch,
                    generation: snapshot.generation,
                    fence_digest: snapshot.fence_digest,
                    deadline_ms: snapshot.deadline_ms,
                },
                receipt: wire_run_receipt(receipt),
            });
        Ok(AgentdPayload::RunReconciliationState { run })
    }
}

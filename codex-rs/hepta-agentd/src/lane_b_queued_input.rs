//! A sealed prepared input retained inside the existing bounded run record.

use super::*;
use crate::canonical_queued_input::CanonicalQueuedRunV1;

impl AgentRunCoordinator {
    /// Restore original completed preparation only after Agentd has validated
    /// an existing Core/Queue preparation origin (or its separate same-turn
    /// never-admitted proof). This internal method grants no dispatch right.
    /// It never downgrades any cancellation, dispatch or terminal observation.
    pub(crate) fn restore_context_attached_prepared(&mut self, now_ms: u64,
        restored: &crate::intelligence_product::RestoredCanonicalPreparationV1,
        queued: CanonicalQueuedRunV1) -> Result<RunReceipt, AgentRunError> {
        if !self.accepting_runs { return Err(AgentRunError::AdmissionClosed); }
        let snapshot = restored.context().original_run_snapshot().clone();
        validate_snapshot(now_ms, &snapshot)?;
        if queued.input.run_id != snapshot.run_id || queued.context != *restored.context() {
            return Err(AgentRunError::MixedSnapshot);
        }
        if self.runs.values().any(|record| record.snapshot.run_id != snapshot.run_id && record.canonical_queued.as_ref().is_some_and(|original|
            original.input.thread_id == queued.input.thread_id && original.input.client_user_message_id == queued.input.client_user_message_id)) {
            return Err(AgentRunError::Conflict);
        }
        let context_digest = Some(restored.context().context_receipt_digest().to_string());
        let compilation_receipt_digest = Some(restored.context().compilation_receipt_digest().to_string());
        if let Some(existing) = self.runs.get_mut(&snapshot.run_id) {
            if existing.phase != RunPhase::ContextAttached || existing.cancel_reason.is_some()
                || existing.cancel_ack_deadline_ms.is_some() || existing.snapshot != snapshot
                || existing.revision != restored.attached_revision() || existing.context_digest != context_digest
                || existing.compilation_receipt_digest != compilation_receipt_digest {
                return Err(AgentRunError::InvalidTransition);
            }
            if existing.canonical_queued.as_ref().is_some_and(|original| original != &queued) {
                return Err(AgentRunError::Conflict);
            }
            existing.canonical_queued = Some(queued);
            return Ok(receipt(existing, /*idempotent*/ false));
        }
        if self.active_run_count() >= self.max_active_runs || self.runs.len() >= MAX_RETAINED_RUNS {
            return Err(AgentRunError::CapacityExceeded);
        }
        let record = RunRecord { snapshot, revision: restored.attached_revision(), phase: RunPhase::ContextAttached,
            context_digest, compilation_receipt_digest, cancel_reason: None, cancel_ack_deadline_ms: None,
            canonical_queued: Some(queued) };
        let result = receipt(&record, /*idempotent*/ false);
        restored.context().verify_run(&result, restored.context().context()).map_err(|_| AgentRunError::MixedSnapshot)?;
        self.runs.insert(record.snapshot.run_id.clone(), record);
        Ok(result)
    }

    pub(crate) fn retain_canonical_queued_input(&mut self, now_ms: u64, queued: CanonicalQueuedRunV1) -> Result<(), AgentRunError> {
        let record = self.runs.get_mut(&queued.input.run_id).ok_or(AgentRunError::RunNotFound)?;
        require_live_deadline(record, now_ms)?;
        if record.phase != RunPhase::ContextAttached || record.cancel_reason.is_some() {
            return Err(AgentRunError::InvalidTransition);
        }
        queued.context.verify_run_snapshot(&record.snapshot)
            .and_then(|()| queued.context.verify_run(&receipt(record, /*idempotent*/ false), queued.context.context()))
            .map_err(|_| AgentRunError::MixedSnapshot)?;
        match &record.canonical_queued {
            Some(existing) if existing == &queued => Ok(()),
            Some(_) => Err(AgentRunError::Conflict),
            None => { record.canonical_queued = Some(queued); Ok(()) }
        }
    }

    pub(crate) fn resolve_canonical_queued_input(&self, now_ms: u64, thread_id: &str, client_id: &str, payload_sha256: &str) -> Result<(RunReceipt, CanonicalQueuedRunV1), AgentRunError> {
        if !self.accepting_runs { return Err(AgentRunError::AdmissionClosed); }
        let mut matching = self.runs.values().filter(|record| record.canonical_queued.as_ref().is_some_and(|queued|
            queued.input.thread_id == thread_id && queued.input.client_user_message_id == client_id));
        let record = matching.next().ok_or(AgentRunError::RunNotFound)?;
        if matching.next().is_some() { return Err(AgentRunError::Conflict); }
        require_live_deadline(record, now_ms)?;
        if record.phase != RunPhase::ContextAttached || record.cancel_reason.is_some() {
            return Err(AgentRunError::InvalidTransition);
        }
        let queued = record.canonical_queued.as_ref().ok_or(AgentRunError::ContextRequired)?;
        if queued.input.input_payload_sha256 != payload_sha256 { return Err(AgentRunError::MixedSnapshot); }
        queued.context.verify_run_snapshot(&record.snapshot)
            .and_then(|()| queued.context.verify_run(&receipt(record, /*idempotent*/ false), queued.context.context()))
            .map_err(|_| AgentRunError::MixedSnapshot)?;
        Ok((receipt(record, /*idempotent*/ false), queued.clone()))
    }
}

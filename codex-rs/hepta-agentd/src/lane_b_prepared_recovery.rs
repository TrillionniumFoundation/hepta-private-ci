//! Explicit same-turn preparation repair. This does not make ordinary
//! dispatched recovery eligible for fresh Queue admission or execution.

use super::*;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::{ProductionDurableWriter, ProductionUnusedScope};
use crate::canonical_queued_input::CanonicalQueuedRunV1;
use crate::intelligence_product::RestoredCanonicalPreparationV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct PreparedRepairTransition { revision: u64 }

impl AgentRunCoordinator {
    /// Continue the original dispatched checkpoint only after the original
    /// Core/Queue boundary and a sealed complete execution frontier agree.
    /// This does not broaden ordinary observation recovery or Queue admission.
    pub(crate) fn resume_verified_checkpoint(
        &mut self,
        now_ms: u64,
        restored: &RestoredCanonicalPreparationV1,
        queued: CanonicalQueuedRunV1,
        evidence: &crate::native_hosted_turn::NativeContinuationEvidence,
        writer: &ProductionDurableWriter,
        scope: &Sha256Digest,
    ) -> Result<RunReceipt, AgentRunError> {
        evidence.verify_binding(writer, scope).map_err(|_| AgentRunError::MixedSnapshot)?;
        if !self.accepting_runs { return Err(AgentRunError::AdmissionClosed); }
        let original = evidence.original();
        validate_recovery(original)?;
        validate_snapshot(now_ms, &original.snapshot)?;
        let attached = restored.attached_run_receipt();
        let first_dispatched_revision = attached.revision.checked_add(1)
            .ok_or(AgentRunError::ArithmeticOverflow)?;
        if original.snapshot != *restored.context().original_run_snapshot()
            || original.cancel_reason.is_some() || original.revision < first_dispatched_revision
            || attached.context_digest.as_deref() != Some(original.context_digest.as_str())
            || attached.compilation_receipt_digest.as_deref() != Some(original.compilation_receipt_digest.as_str())
            || queued.input.run_id != original.snapshot.run_id || queued.context != *restored.context()
        {
            return Err(AgentRunError::MixedSnapshot);
        }
        if self.runs.values().any(|record| record.snapshot.run_id != original.snapshot.run_id
            && record.canonical_queued.as_ref().is_some_and(|previous|
                previous.input.thread_id == queued.input.thread_id
                    && previous.input.client_user_message_id == queued.input.client_user_message_id))
        {
            return Err(AgentRunError::Conflict);
        }
        let record = if let Some(existing) = self.runs.get(&original.snapshot.run_id) {
            if existing.revision < original.revision
                || existing.canonical_queued.as_ref().is_some_and(|previous| previous != &queued)
            {
                return Err(AgentRunError::Conflict);
            }
            let transition = prepared_repair_transition(now_ms, &original.snapshot, &attached, existing)?;
            let mut resumed = existing.clone();
            resumed.phase = RunPhase::Dispatched;
            resumed.revision = transition.revision;
            resumed.canonical_queued = Some(queued);
            resumed
        } else {
            if self.active_run_count() >= self.max_active_runs || self.runs.len() >= MAX_RETAINED_RUNS {
                return Err(AgentRunError::CapacityExceeded);
            }
            RunRecord {
                snapshot: original.snapshot.clone(),
                revision: original.revision.checked_add(1).ok_or(AgentRunError::ArithmeticOverflow)?,
                phase: RunPhase::Dispatched,
                context_digest: Some(original.context_digest.clone()),
                compilation_receipt_digest: Some(original.compilation_receipt_digest.clone()),
                cancel_reason: None, cancel_ack_deadline_ms: None, canonical_queued: Some(queued),
            }
        };
        let result = receipt(&record, /*idempotent*/ false);
        self.runs.insert(record.snapshot.run_id.clone(), record);
        Ok(result)
    }

    /// Only Agentd's retained Core/Queue boundary calls this method after
    /// authenticating the original signed input and deriving its exact scope
    /// from Core's private original provenance. The opaque proof must come
    /// from the original production writer, never from checkpoint absence.
    pub(crate) fn resume_prepared_without_operations(
        &mut self,
        now_ms: u64,
        restored: &RestoredCanonicalPreparationV1,
        queued: CanonicalQueuedRunV1,
        unused: &ProductionUnusedScope,
        writer: &ProductionDurableWriter,
        scope: &Sha256Digest,
    ) -> Result<RunReceipt, AgentRunError> {
        unused.verify_binding(writer, scope).map_err(|_| AgentRunError::MixedSnapshot)?;
        if !self.accepting_runs { return Err(AgentRunError::AdmissionClosed); }
        let snapshot = restored.context().original_run_snapshot();
        validate_snapshot(now_ms, snapshot)?;
        if queued.input.run_id != snapshot.run_id || queued.context != *restored.context() {
            return Err(AgentRunError::MixedSnapshot);
        }
        if self.runs.values().any(|record| record.snapshot.run_id != snapshot.run_id
            && record.canonical_queued.as_ref().is_some_and(|original|
                original.input.thread_id == queued.input.thread_id
                    && original.input.client_user_message_id == queued.input.client_user_message_id))
        {
            return Err(AgentRunError::Conflict);
        }
        let existing = self.runs.get(&snapshot.run_id);
        if existing.is_none() {
            // The same strict reducer preserves the actual journaled revision
            // and rejects cancellation, conflicts and any altered snapshot.
            return self.restore_context_attached_prepared(now_ms, restored, queued);
        }
        if existing.is_some_and(|record| record.phase == RunPhase::ContextAttached) {
            // A previous Core task may still hold an initial plan whose
            // predicted dispatch revision is attached+1. The new reserved task
            // must move strictly past that value before releasing its proof.
            let revision = replacement_attachment_revision(restored.attached_revision())?;
            self.restore_context_attached_prepared(now_ms, restored, queued)?;
            let record = self.runs.get_mut(&snapshot.run_id).ok_or(AgentRunError::RunNotFound)?;
            record.phase = RunPhase::Dispatched;
            record.revision = revision;
            return Ok(receipt(record, /*idempotent*/ false));
        }
        let existing = existing.ok_or(AgentRunError::RunNotFound)?;
        if existing.canonical_queued.as_ref().is_some_and(|original| original != &queued) {
            return Err(AgentRunError::Conflict);
        }
        let attached = restored.attached_run_receipt();
        let transition = prepared_repair_transition(now_ms, snapshot, &attached, existing)?;
        // All fallible identity/currentness checks precede this mutation.
        // Keep the dispatched identity; every newly reserved Core task
        // advances revision, invalidating old holders without another run.
        let record = self.runs.get_mut(&snapshot.run_id).ok_or(AgentRunError::RunNotFound)?;
        record.phase = RunPhase::Dispatched;
        record.revision = transition.revision;
        record.canonical_queued = Some(queued);
        Ok(receipt(record, /*idempotent*/ false))
    }
}

fn replacement_attachment_revision(attached: u64) -> Result<u64, AgentRunError> {
    attached.checked_add(2).ok_or(AgentRunError::ArithmeticOverflow)
}

/// Pure lifecycle validation. This produces no sealed handoff or authority;
/// the caller still requires the original writer proof before applying it.
fn prepared_repair_transition(
    now_ms: u64,
    snapshot: &RunSnapshot,
    attached: &RunReceipt,
    existing: &RunRecord,
) -> Result<PreparedRepairTransition, AgentRunError> {
    validate_snapshot(now_ms, snapshot)?;
    if existing.snapshot != *snapshot
        || existing.context_digest != attached.context_digest
        || existing.compilation_receipt_digest != attached.compilation_receipt_digest
        || attached.context_digest.is_none() || attached.compilation_receipt_digest.is_none()
    {
        return Err(AgentRunError::MixedSnapshot);
    }
    if existing.cancel_reason.is_some() || existing.cancel_ack_deadline_ms.is_some() {
        return Err(AgentRunError::InvalidTransition);
    }
    let first_dispatched_revision = attached.revision.checked_add(1)
        .ok_or(AgentRunError::ArithmeticOverflow)?;
    if existing.revision < first_dispatched_revision {
        return Err(AgentRunError::StaleRevision);
    }
    match existing.phase {
        RunPhase::Dispatched | RunPhase::Indeterminate => Ok(PreparedRepairTransition {
            revision: existing.revision.checked_add(1).ok_or(AgentRunError::ArithmeticOverflow)?,
        }),
        _ => Err(AgentRunError::InvalidTransition),
    }
}

#[cfg(test)]
#[path = "lane_b_prepared_recovery_tests.rs"]
mod tests;

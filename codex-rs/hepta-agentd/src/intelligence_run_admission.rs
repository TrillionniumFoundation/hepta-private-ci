//! Atomic canonical run/context publication under the existing run owner.
//! This is not another coordinator and does not authorize physical dispatch.

use super::*;
use crate::intelligence_identity::AgentdRunEpochV1;

impl AgentRunCoordinator {
    pub(crate) fn bind_run_epoch(&mut self, epoch: AgentdRunEpochV1) -> Result<(), AgentRunError> {
        epoch.validate_composition(&self.composition)?;
        if let Some(current) = &self.run_epoch {
            if current != &epoch {
                return Err(AgentRunError::MixedSnapshot);
            }
            return Ok(());
        }
        if !self.runs.is_empty() {
            return Err(AgentRunError::InvalidTransition);
        }
        self.run_epoch = Some(epoch);
        Ok(())
    }

    pub(super) fn require_composition_identity(
        &self,
        snapshot: &RunSnapshot,
    ) -> Result<(), AgentRunError> {
        if let Some(epoch) = &self.run_epoch {
            epoch.validate_composition(&self.composition)?;
            epoch.validate_snapshot(snapshot)?;
        }
        Ok(())
    }

    pub(crate) fn admit_intelligence_context(
        &mut self,
        now_ms: u64,
        snapshot: RunSnapshot,
        context: ContextAttachment,
    ) -> Result<RunReceipt, AgentRunError> {
        if self.run_epoch.is_none() {
            return Err(AgentRunError::InvalidGeneration);
        }
        self.require_composition_identity(&snapshot)?;
        validate_snapshot_fields(&snapshot)?;
        validate_attachment(&context)?;
        if context.run_id != snapshot.run_id
            || context.request_digest != snapshot.request_digest
            || context.objective_digest != snapshot.objective_digest
            || context.body_digest != snapshot.body_digest
            || context.artifact_set_digest != snapshot.artifact_set_digest
            || context.authority_epoch != snapshot.authority_epoch
            || context.generation != snapshot.generation
            || context.fence_digest != snapshot.fence_digest
            || context.deadline_ms != snapshot.deadline_ms
        {
            return Err(AgentRunError::MixedSnapshot);
        }
        if let Some(existing) = self.runs.get(&snapshot.run_id) {
            if existing.snapshot == snapshot
                && existing.context_digest.as_deref() == Some(context.context_digest.as_str())
                && existing.compilation_receipt_digest.as_deref()
                    == Some(context.compilation_receipt_digest.as_str())
            {
                // A replay returns its current phase, including terminal or
                // Indeterminate; it never resets the run to ContextAttached.
                return Ok(receipt(existing, /*idempotent*/ true));
            }
            return Err(AgentRunError::Conflict);
        }
        validate_snapshot(now_ms, &snapshot)?;
        if !self.accepting_runs {
            return Err(AgentRunError::AdmissionClosed);
        }
        if self.active_run_count() >= self.max_active_runs || self.runs.len() >= MAX_RETAINED_RUNS {
            return Err(AgentRunError::CapacityExceeded);
        }
        let record = RunRecord {
            snapshot: snapshot.clone(),
            revision: 2,
            phase: RunPhase::ContextAttached,
            context_digest: Some(context.context_digest),
            compilation_receipt_digest: Some(context.compilation_receipt_digest),
            cancel_reason: None,
            cancel_ack_deadline_ms: None,
        };
        let result = receipt(&record, /*idempotent*/ false);
        self.runs.insert(snapshot.run_id, record);
        Ok(result)
    }
}

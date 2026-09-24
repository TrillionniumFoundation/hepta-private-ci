//! One projection of a revalidated durable owner record into the run coordinator.
//! This does not authenticate records; the daemon rechecks AuthBus and Fleet.
use super::AgentRunError;
use super::RunSnapshot;
use codex_hepta_learning_ledger::RunStartObjectiveDispositionV1;
use codex_hepta_learning_ledger::RunStartRecordV1;

impl RunSnapshot {
    pub(crate) fn from_revalidated_run_start(
        record: &RunStartRecordV1,
    ) -> Result<Self, AgentRunError> {
        if record.objective_function_v1_digest.is_zero()
            || record.objective_function_v1_bytes.is_empty()
        {
            return Err(AgentRunError::InvalidRunStart(
                "canonical ObjectiveFunctionV1 identity",
            ));
        }
        if record.disposition != RunStartObjectiveDispositionV1::Compiled {
            return Err(AgentRunError::InvalidRunStart("objective disposition"));
        }
        if record.admission.authority.grants_any() {
            return Err(AgentRunError::InvalidRunStart("authority"));
        }
        let deadline_ms = record
            .admission
            .deadline_unix_micros
            .checked_add(999)
            .map(|value| value / 1_000)
            .ok_or(AgentRunError::ArithmeticOverflow)?;
        Ok(Self {
            run_id: record.snapshot.run_id.to_string(),
            request_digest: record.admission.admitted_source_digest.to_string(),
            objective_digest: record.snapshot.objective_digest.to_string(),
            body_digest: record.runtime_body_digest.to_string(),
            artifact_set_digest: record.snapshot.artifact_set_digest.to_string(),
            authority_epoch: record.snapshot.authority_epoch,
            generation: record.snapshot.generation,
            fence_digest: record.snapshot.fence_digest.to_string(),
            deadline_ms,
        })
    }
}

impl From<super::RunSnapshot> for crate::AgentRunSnapshot {
    fn from(value: super::RunSnapshot) -> Self {
        Self {
            run_id: value.run_id,
            request_digest: value.request_digest,
            objective_digest: value.objective_digest,
            body_digest: value.body_digest,
            artifact_set_digest: value.artifact_set_digest,
            authority_epoch: value.authority_epoch,
            generation: value.generation,
            fence_digest: value.fence_digest,
            deadline_ms: value.deadline_ms,
        }
    }
}

impl From<crate::AgentRunSnapshot> for super::RunSnapshot {
    fn from(value: crate::AgentRunSnapshot) -> Self {
        Self {
            run_id: value.run_id,
            request_digest: value.request_digest,
            objective_digest: value.objective_digest,
            body_digest: value.body_digest,
            artifact_set_digest: value.artifact_set_digest,
            authority_epoch: value.authority_epoch,
            generation: value.generation,
            fence_digest: value.fence_digest,
            deadline_ms: value.deadline_ms,
        }
    }
}

impl From<crate::AgentContextAttachment> for super::ContextAttachment {
    fn from(value: crate::AgentContextAttachment) -> Self {
        Self {
            run_id: value.run_id,
            request_digest: value.request_digest,
            objective_digest: value.objective_digest,
            body_digest: value.body_digest,
            artifact_set_digest: value.artifact_set_digest,
            authority_epoch: value.authority_epoch,
            generation: value.generation,
            fence_digest: value.fence_digest,
            deadline_ms: value.deadline_ms,
            context_digest: value.context_digest,
            compilation_receipt_digest: value.compilation_receipt_digest,
        }
    }
}

impl From<super::ContextAttachment> for crate::AgentContextAttachment {
    fn from(value: super::ContextAttachment) -> Self {
        Self {
            run_id: value.run_id,
            request_digest: value.request_digest,
            objective_digest: value.objective_digest,
            body_digest: value.body_digest,
            artifact_set_digest: value.artifact_set_digest,
            authority_epoch: value.authority_epoch,
            generation: value.generation,
            fence_digest: value.fence_digest,
            deadline_ms: value.deadline_ms,
            context_digest: value.context_digest,
            compilation_receipt_digest: value.compilation_receipt_digest,
        }
    }
}

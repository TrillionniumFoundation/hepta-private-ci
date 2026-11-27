//! Canonical preparation bound to an already-published durable RunStart.
//!
//! Agentd performs the real signature, current generation and fence checks both
//! before owner preparation and immediately before runtime admission. This
//! adapter preserves the original record; it never refreshes an old identity.

use codex_hepta_learning_ledger::RunStartRecordV1;

use super::*;

impl AgentdIntelligenceProductRunnerV1 {
    pub(crate) async fn prepare_for_run_start(
        &self,
        composition: &crate::RuntimeComposition,
        record: &RunStartRecordV1,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
        let original = original_run_identity(record)?;
        if request.run_id != record.snapshot.run_id
            || request.snapshot.objective_digest() != record.snapshot.objective_digest
            || request.snapshot.authority_epoch() != record.snapshot.authority_epoch
            || request.snapshot.body_generation().get() != composition.agentd_generation
        {
            return Err(AgentdIntelligenceProductError::Run(
                crate::AgentRunError::MixedSnapshot,
            ));
        }
        self.prepare_with_run_identity(composition, Some(original), request, inputs)
            .await
    }
}

impl PreparedAgentdIntelligenceRunV1 {
    /// Validate before either coordinator mutation so a mixed preparation
    /// cannot consume admission capacity and only fail later at attachment.
    pub(crate) fn require_original_run_start(
        &self,
        record: &RunStartRecordV1,
    ) -> Result<(), AgentdIntelligenceProductError> {
        let original = original_run_identity(record)?;
        let attachment = &self.context_attachment;
        if self.run_snapshot != original
            || attachment.run_id != original.run_id
            || attachment.request_digest != original.request_digest
            || attachment.objective_digest != original.objective_digest
            || attachment.body_digest != original.body_digest
            || attachment.artifact_set_digest != original.artifact_set_digest
            || attachment.authority_epoch != original.authority_epoch
            || attachment.generation != original.generation
            || attachment.fence_digest != original.fence_digest
            || attachment.deadline_ms != original.deadline_ms
            || attachment.context_digest != self.envelope.context_receipt_digest.to_string()
            || attachment.compilation_receipt_digest != self.envelope.envelope_digest.to_string()
        {
            return Err(AgentdIntelligenceProductError::Run(
                crate::AgentRunError::MixedSnapshot,
            ));
        }
        Ok(())
    }
}

fn original_run_identity(
    record: &RunStartRecordV1,
) -> Result<crate::AgentRunSnapshot, AgentdIntelligenceProductError> {
    let original =
        crate::RunSnapshot::from_run_start(record).map_err(AgentdIntelligenceProductError::Run)?;
    Ok(crate::AgentRunSnapshot {
        run_id: original.run_id,
        request_digest: original.request_digest,
        objective_digest: original.objective_digest,
        body_digest: original.body_digest,
        artifact_set_digest: original.artifact_set_digest,
        authority_epoch: original.authority_epoch,
        generation: original.generation,
        fence_digest: original.fence_digest,
        deadline_ms: original.deadline_ms,
    })
}

pub(super) fn remaining_preparation_budget(
    now_ms: u64,
    original_deadline_ms: u64,
    requested_micros: u64,
) -> Result<u64, AgentdIntelligenceProductError> {
    let remaining_ms = original_deadline_ms
        .checked_sub(now_ms)
        .filter(|value| *value > 0)
        .ok_or(AgentdIntelligenceProductError::Run(
            crate::AgentRunError::InvalidDeadline,
        ))?;
    Ok(requested_micros.min(remaining_ms.saturating_mul(1_000)))
}

#[cfg(test)]
#[path = "intelligence_run_start_tests.rs"]
mod tests;

//! Revalidate the original signed preparation before the same logical turn
//! continues from an independently verified original checkpoint frontier.

use super::*;
use codex_core::hosted_turn::HostedCheckpointContinuationInput;
use codex_hepta_memory::ProductionDurableWriter;
use crate::canonical_queued_input::{CanonicalQueuedRunV1, queued_input, verify_admitted_record};
use crate::intelligence_product::RestoredCanonicalPreparationV1;
use crate::native_hosted_turn::NativeContinuationEvidence;

fn continuation_error(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(format!("original native checkpoint continuation: {error}"))
}

impl AgentdState {
    pub(crate) fn restore_native_checkpoint_continuation(&self,
        input: &HostedCheckpointContinuationInput,
        restored: &RestoredCanonicalPreparationV1,
        evidence: &NativeContinuationEvidence,
        writer: &ProductionDurableWriter) -> Result<RunReceipt, AgentdError> {
        input.origin.validate(&input.observation).map_err(continuation_error)?;
        let observation = &input.observation;
        let anchor = evidence.anchor();
        if input.cancellation.is_cancelled()
            || input.origin.original_recovery() != &observation.recovery
            || anchor.recovery != observation.recovery
            || anchor.checkpoint.thread_id != observation.thread_id
            || anchor.checkpoint.turn_id != observation.turn_id
            || anchor.queue.as_ref().is_none_or(|queue|
                queue.queued_item_id != observation.queue.queued_item_id
                    || queue.client_id != observation.queue.client_id
                    || queue.payload_sha256 != observation.queue.payload_sha256)
        {
            return Err(continuation_error("Core changed or cancelled its original retained turn"));
        }
        let execution = anchor.execution.as_ref()
            .ok_or_else(|| continuation_error("original execution scope is absent"))?;
        let scope = crate::NativeTurnScope {
            cell_id: StableId::new(execution.cell_id.clone()).map_err(continuation_error)?,
            organ_id: StableId::new(execution.organ_id.clone()).map_err(continuation_error)?,
            final_scope_id: StableId::new(execution.final_scope_id.clone()).map_err(continuation_error)?,
        };
        let scope_digest = crate::native_admission::execution_scope_digest(&anchor.checkpoint,
            &restored.attached_run_receipt(), writer.owner_agent_id(), &scope,
            Generation::new(execution.policy_generation).map_err(continuation_error)?)
            .map_err(continuation_error)?;
        let scope_digest = Sha256Digest::parse(scope_digest.to_string()).map_err(continuation_error)?;
        evidence.verify_binding(writer, &scope_digest).map_err(continuation_error)?;
        let current = self.load_canonical_prepared_for_queue(&observation.thread_id.to_string(),
            &observation.queue.client_id, &observation.queue.payload_sha256)?
            .ok_or_else(|| continuation_error("original canonical preparation is not durable"))?;
        if current.prepared() != restored.prepared()
            || current.attached_revision() != restored.attached_revision()
            || current.context() != restored.context()
            || &evidence.original().snapshot != restored.context().original_run_snapshot()
        {
            return Err(continuation_error("checkpoint differs from this owner's original preparation"));
        }
        let host = self.objective_runtime.get()
            .ok_or_else(|| continuation_error("original Objective owner is unavailable"))?;
        let original = host.original_record(&evidence.original().snapshot.run_id)?;
        self.require_current_run_start(&original)?;
        verify_admitted_record(&original, &evidence.original().snapshot).map_err(continuation_error)?;
        let expected = queued_input(&self.identity, &original).map_err(continuation_error)?;
        if expected.thread_id != observation.thread_id.to_string()
            || expected.client_user_message_id != observation.queue.client_id
            || expected.input_payload_sha256 != observation.queue.payload_sha256
        {
            return Err(continuation_error("original signed Queue identity changed"));
        }
        let context = crate::canonical_queued_input::bind_selected_text(&original, restored.prepared())
            .map_err(continuation_error)?;
        if &context != restored.context() {
            return Err(continuation_error("original signed source material changed"));
        }
        // Same existing owner order: retained writer fence -> original journal -> runtime -> runs.
        // The entry gate repeats live AuthBus/Fleet/Core checks at physical use.
        self.with_fresh_original_run(&evidence.original().snapshot.run_id, || {
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        if runtime.lifecycle != AgentLifecycle::Running || runtime.fenced
            || !runtime.app_server_ready || !runtime.critical_stores_ready
            || !runtime.revocation_ready || !runtime.required_ports_ready || !runtime.admission_open
        {
            return Err(continuation_error("original owner is not ready for checkpoint continuation"));
        }
        let now_ms = unix_now_ms()?;
        self.authenticate_current_run_start(&original, runtime.current_generation, now_ms)?;
        if evidence.original().snapshot.generation != runtime.current_generation
            || input.cancellation.is_cancelled()
        {
            return Err(continuation_error("original continuation was cancelled or its generation changed"));
        }
        let mut runs = self.runs.lock().map_err(poisoned_state)?;
        runs.resume_verified_checkpoint(now_ms, restored, CanonicalQueuedRunV1 { input: expected, context },
            evidence, writer, &scope_digest).map_err(run_error)
        })
    }
}

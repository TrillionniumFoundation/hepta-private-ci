//! Repair only the original Core turn's preparation, using the original
//! writer's positive immutable-ledger evidence that its scope was never used.
//! Missing checkpoint files alone never authorize this reducer.

use super::*;
use codex_core::hosted_turn::HostedTurnInput;
use codex_hepta_memory::{ProductionDurableWriter, ProductionUnusedScope};
use crate::canonical_queued_input::{CanonicalQueuedRunV1, queued_input, verify_admitted_record};
use crate::intelligence_product::RestoredCanonicalPreparationV1;

fn preparation_error(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(format!("original native preparation repair: {error}"))
}

impl AgentdState {
    /// The caller holds Core's original same-turn reservation and Queue's
    /// original dispatch lock. The borrowed writer proof keeps the original
    /// lease live through this mutation; it is not an execution permit. The
    /// physical model/process entry must still pass the existing owner gate.
    pub(crate) fn restore_native_preparation(
        &self,
        input: &HostedTurnInput,
        restored: &RestoredCanonicalPreparationV1,
        unused: &ProductionUnusedScope,
        writer: &ProductionDurableWriter,
        scope: &Sha256Digest,
    ) -> Result<RunReceipt, AgentdError> {
        input.origin.validate(input.thread_id, &input.turn_id, &input.queue)
            .map_err(preparation_error)?;
        input.origin.require_retained().map_err(preparation_error)?;
        if input.cancellation.is_cancelled() {
            return Err(preparation_error("original Core turn was cancelled"));
        }
        let expected_scope = crate::native_hosted_turn::retained_preparation_scope(input, restored, writer)
            .map_err(preparation_error)?;
        if scope != &expected_scope {
            return Err(preparation_error("unused-scope evidence belongs to another original turn or scope"));
        }
        unused.verify_binding(writer, &expected_scope).map_err(preparation_error)?;

        let payload = codex_protocol::user_input::user_input_payload_sha256(&input.input)
            .map_err(preparation_error)?;
        if payload != input.queue.payload_sha256 {
            return Err(preparation_error("original Core input changed after Queue admission"));
        }
        // Read this state's original journal again. A sealed preparation from
        // another host or an earlier read cannot replace the original owner.
        // This also repeats all seven owner freshness checks without executing
        // any owner stage or issuing a new decision/selection receipt.
        let current = self.load_canonical_prepared_for_queue(
            &input.thread_id.to_string(), &input.queue.client_id, &payload)?
            .ok_or_else(|| preparation_error("original completed preparation is not durable"))?;
        if current.prepared() != restored.prepared()
            || current.attached_revision() != restored.attached_revision()
            || current.context() != restored.context()
        {
            return Err(preparation_error("restored preparation differs from this original journal"));
        }
        let host = self.objective_runtime.get()
            .ok_or_else(|| preparation_error("original Objective owner is unavailable"))?;
        let original = host.original_record(&restored.context().original_run_snapshot().run_id)?;
        self.require_current_run_start(&original)?;
        verify_admitted_record(&original, restored.context().original_run_snapshot())
            .map_err(preparation_error)?;
        let expected = queued_input(&self.identity, &original).map_err(preparation_error)?;
        if expected.thread_id != input.thread_id.to_string()
            || expected.client_user_message_id != input.queue.client_id
            || expected.input_payload_sha256 != payload
        {
            return Err(preparation_error("original signed queue identity changed"));
        }
        let context = crate::canonical_queued_input::bind_selected_text(&original, restored.prepared())
            .map_err(preparation_error)?;
        if &context != restored.context() {
            return Err(preparation_error("original signed source material changed"));
        }

        // Existing lock order: retained writer lease -> original journal -> runtime -> runs.
        // AuthBus publishers do not share this lock protocol; currentness is
        // an entry-time snapshot, rechecked at the physical effect boundary.
        self.with_fresh_original_run(&restored.context().original_run_snapshot().run_id, || {
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        if runtime.lifecycle != AgentLifecycle::Running || runtime.fenced
            || !runtime.app_server_ready || !runtime.critical_stores_ready
            || !runtime.revocation_ready || !runtime.required_ports_ready || !runtime.admission_open
        {
            return Err(preparation_error("original owner is not ready for preparation recovery"));
        }
        let now_ms = unix_now_ms()?;
        self.authenticate_current_run_start(&original, runtime.current_generation, now_ms)?;
        if restored.context().original_run_snapshot().generation != runtime.current_generation {
            return Err(preparation_error("compiled preparation generation is no longer current"));
        }
        if input.cancellation.is_cancelled() {
            return Err(preparation_error("original Core turn was cancelled during recovery"));
        }
        let mut runs = self.runs.lock().map_err(poisoned_state)?;
        runs.resume_prepared_without_operations(now_ms, restored,
            CanonicalQueuedRunV1 { input: expected, context }, unused, writer, &expected_scope)
            .map_err(run_error)
        })
    }
}

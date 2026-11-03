//! Resolve the signed input through the original journal and run coordinator.

use super::*;
use crate::NativeContextBindingV1;
use crate::PreparedAgentdIntelligenceRunV1;
use crate::canonical_queued_input::CanonicalQueuedInputV1;
use crate::canonical_queued_input::CanonicalQueuedRunV1;
use crate::canonical_queued_input::queued_input;
use crate::canonical_queued_input::verify_admitted_record;
use crate::intelligence_product::RestoredCanonicalPreparationV1;
use codex_core::hosted_turn::HostedTurnInput;
use codex_hepta_learning_ledger::CommittedRunPreparedV1;

fn original_input_error(error: anyhow::Error) -> AgentdError {
    AgentdError::Invalid(format!("original canonical queued input: {error:#}"))
}

impl AgentdState {
    /// Recover completed preparation facts only from this original Objective
    /// owner's journal. Queue/turn admission is deliberately a separate step.
    pub(crate) fn load_canonical_prepared(
        &self,
        run_id: &str,
    ) -> Result<Option<crate::intelligence_product::RestoredCanonicalPreparationV1>, AgentdError>
    {
        let host = self.objective_runtime.get().ok_or_else(|| {
            AgentdError::Invalid("original Objective owner is unavailable".to_owned())
        })?;
        let Some(committed) = host.committed_prepared(run_id)? else {
            return Ok(None);
        };
        self.validate_committed_preparation(&committed).map(Some)
    }

    pub(crate) fn load_canonical_prepared_for_queue(
        &self,
        thread_id: &str,
        client_id: &str,
        payload_sha256: &str,
    ) -> Result<Option<RestoredCanonicalPreparationV1>, AgentdError> {
        let host = self.objective_runtime.get().ok_or_else(|| {
            AgentdError::Invalid("original Objective owner is unavailable".to_owned())
        })?;
        let Some(committed) = host.committed_prepared_for_queue(
            &self.identity,
            thread_id,
            client_id,
            payload_sha256,
        )?
        else {
            return Ok(None);
        };
        self.validate_committed_preparation(&committed).map(Some)
    }

    fn validate_committed_preparation(
        &self,
        committed: &CommittedRunPreparedV1,
    ) -> Result<RestoredCanonicalPreparationV1, AgentdError> {
        let now_ms = self.require_current_run_start(committed.original())?;
        let runner = self.intelligence_product.get().ok_or_else(|| {
            AgentdError::Invalid("original canonical owner runner is unavailable".to_owned())
        })?;
        let restored = runner
            .restore_canonical_handoff(committed, committed.original().snapshot.generation, now_ms)
            .map_err(original_input_error)?;
        let after = self.require_current_run_start(committed.original())?;
        if restored.context().original_run_snapshot().deadline_ms <= after {
            return Err(AgentdError::Invalid(
                "original compiled canonical handoff expired during recovery".to_owned(),
            ));
        }
        Ok(restored)
    }

    pub(crate) fn canonical_queued_input(
        &self,
        record: &RunStartRecordV1,
    ) -> Result<CanonicalQueuedInputV1, AgentdError> {
        self.require_current_run_start(record)?;
        queued_input(&self.identity, record).map_err(original_input_error)
    }

    pub(crate) fn retain_canonical_queued_input(
        &self,
        record: &RunStartRecordV1,
        prepared: &PreparedAgentdIntelligenceRunV1,
    ) -> Result<(), AgentdError> {
        let now_ms = self.require_current_run_start(record)?;
        let input = queued_input(&self.identity, record).map_err(original_input_error)?;
        let restored = self
            .load_canonical_prepared(record.snapshot.run_id.as_str())?
            .ok_or_else(|| {
                AgentdError::Invalid(
                    "original canonical preparation is not durable; outcome remains unknown"
                        .to_owned(),
                )
            })?;
        if restored.prepared() != prepared {
            return Err(AgentdError::Invalid(
                "prepared handoff differs from original durable owner state".to_owned(),
            ));
        }
        let context = restored.context().clone();
        verify_admitted_record(record, context.original_run_snapshot())
            .map_err(original_input_error)?;
        self.with_fresh_original_run(record.snapshot.run_id.as_str(), || {
            self.runs
                .lock()
                .map_err(poisoned_state)?
                .retain_canonical_queued_input(now_ms, CanonicalQueuedRunV1 { input, context })
                .map_err(run_error)
        })
    }

    /// A cold projection is allowed only at the original Core's initial
    /// preparation boundary under its original Queue dispatch ownership.
    /// Retained-turn repair uses a separate positive never-admitted proof.
    pub(crate) fn resolve_canonical_queued_input(
        &self,
        input: &HostedTurnInput,
    ) -> Result<(RunReceipt, NativeContextBindingV1), AgentdError> {
        input
            .origin
            .validate(input.thread_id, &input.turn_id, &input.queue)
            .map_err(|error| {
                AgentdError::Invalid(format!("original Core preparation origin: {error}"))
            })?;
        if input.cancellation.is_cancelled() {
            return Err(AgentdError::Invalid(
                "original Core preparation was cancelled".to_owned(),
            ));
        }
        let actual_payload = codex_protocol::user_input::user_input_payload_sha256(&input.input)
            .map_err(|error| AgentdError::Invalid(format!("original Core payload: {error}")))?;
        if actual_payload != input.queue.payload_sha256 {
            return Err(AgentdError::Invalid(
                "original Core input changed after Queue admission".to_owned(),
            ));
        }
        let restored = self
            .load_canonical_prepared_for_queue(
                &input.thread_id.to_string(),
                &input.queue.client_id,
                &actual_payload,
            )?
            .ok_or_else(|| {
                AgentdError::Invalid(
                    "original canonical preparation is not durable; outcome remains unknown"
                        .to_owned(),
                )
            })?;
        let host = self.objective_runtime.get().ok_or_else(|| {
            AgentdError::Invalid("original Objective owner is unavailable".to_owned())
        })?;
        let original = host.original_record(&restored.context().original_run_snapshot().run_id)?;
        self.require_current_run_start(&original)?;
        let expected = queued_input(&self.identity, &original).map_err(original_input_error)?;
        if expected.thread_id != input.thread_id.to_string()
            || expected.client_user_message_id != input.queue.client_id
            || expected.input_payload_sha256 != actual_payload
        {
            return Err(AgentdError::Invalid(
                "original signed queue identity changed".to_owned(),
            ));
        }
        let original_context =
            crate::canonical_queued_input::bind_selected_text(&original, restored.prepared())
                .map_err(original_input_error)?;
        if &original_context != restored.context() {
            return Err(AgentdError::Invalid(
                "original signed source material changed".to_owned(),
            ));
        }
        self.with_fresh_original_run(original.snapshot.run_id.as_str(), || {
            let runtime = self.runtime.lock().map_err(poisoned_state)?;
            if runtime.lifecycle != AgentLifecycle::Running
                || runtime.fenced
                || !runtime.app_server_ready
                || !runtime.critical_stores_ready
                || !runtime.revocation_ready
                || !runtime.required_ports_ready
                || !runtime.admission_open
            {
                return Err(AgentdError::Invalid(
                    "original canonical recovery owner is not ready".to_owned(),
                ));
            }
            let now_ms = unix_now_ms()?;
            self.authenticate_current_run_start(&original, runtime.current_generation, now_ms)?;
            let context = restored.context().clone();
            let mut runs = self.runs.lock().map_err(poisoned_state)?;
            if runs.run(&original.snapshot.run_id.to_string()).is_none() {
                input.origin.require_initial().map_err(|error| {
                    AgentdError::Invalid(format!("cold canonical preparation origin: {error}"))
                })?;
            }
            // A retained-turn origin reaches this warm branch only after its
            // separate original-writer proof restored the same prepared run.
            // The reducer still rejects every dispatched/cancelled/terminal phase.
            let run = runs
                .restore_context_attached_prepared(
                    now_ms,
                    &restored,
                    CanonicalQueuedRunV1 {
                        input: expected,
                        context: context.clone(),
                    },
                )
                .map_err(run_error)?;
            Ok((run, context))
        })
    }
}

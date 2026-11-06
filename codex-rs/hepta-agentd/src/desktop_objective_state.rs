//! Finite two-destination execution by the same original Objective coordinator.
use super::*;
use crate::ContextAttachment;
use crate::RunPhase;
use codex_hepta_learning_ledger::RunStartObjectiveDispositionV1;
use codex_hepta_memory::CalculatorTargetIdentity;
use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_memory::NotesTargetIdentity;
use codex_hepta_memory::ProductionRetainedOperation;

#[derive(Clone, Debug)]
pub struct AgentdDesktopObjectiveConfig {
    pub profile_digest: Digest32,
    pub notes: NotesTargetIdentity,
    pub calculator: CalculatorTargetIdentity,
}

impl AgentdDesktopObjectiveConfig {
    pub(crate) fn validate(&self) -> Result<(), AgentdError> {
        self.notes.validate().map_err(AgentdError::Invalid)?;
        self.calculator.validate().map_err(AgentdError::Invalid)?;
        if self.profile_digest.is_zero()
            || self.notes.session_instance != self.calculator.session_instance
            || self.notes.task_id != 1
            || self.calculator.task_id != 2
            || self.notes.incarnation == self.calculator.incarnation
        {
            return Err(AgentdError::Invalid(
                "Desktop profile has no exact joint Session targets".into(),
            ));
        }
        Ok(())
    }

    pub(crate) fn validate_host(
        &self,
        host: &crate::AgentdProductionWriterHost,
    ) -> Result<(), AgentdError> {
        self.validate()?;
        if host.destination_count() != 2
            || !host.has_destination(&self.notes.destination_id())
            || !host.has_destination(&self.calculator.destination_id())
        {
            return Err(AgentdError::Invalid(
                "Desktop requires exactly its two original destinations".into(),
            ));
        }
        Ok(())
    }
}

impl AgentdState {
    pub(crate) async fn validate_desktop_source(
        &self,
        profile_digest: Digest32,
        run_id: &str,
        source_digest: Digest32,
        source_json: &str,
    ) -> Result<(), AgentdError> {
        if let Some(config) = self.desktop_objective.get() {
            if config.profile_digest != profile_digest {
                return Err(AgentdError::Invalid(
                    "Desktop profile differs from registered Objective profile".into(),
                ));
            }
            let operation = self
                .checked_desktop_operation(config, run_id, source_digest)
                .await?;
            let action = match operation.topic.as_str() {
                codex_hepta_memory::NOTES_REPLACE_TOPIC_V1 => "notes.replace",
                codex_hepta_memory::CALCULATOR_EVALUATE_TOPIC_V1 => "calculator.evaluate",
                _ => return Err(AgentdError::Invalid("unregistered Desktop action".into())),
            };
            let source: serde_json::Value = serde_json::from_str(source_json)?;
            if source["structuredIntent"]["legalActionClasses"] != serde_json::json!([action]) {
                return Err(AgentdError::Invalid(
                    "Desktop Objective action differs from its exact original operation".into(),
                ));
            }
        }
        Ok(())
    }

    async fn checked_desktop_operation(
        &self,
        config: &AgentdDesktopObjectiveConfig,
        run_id: &str,
        source_digest: Digest32,
    ) -> Result<ProductionRetainedOperation, AgentdError> {
        let host = self
            .production_operations
            .get()
            .ok_or_else(|| AgentdError::Protocol("Desktop original owner unavailable".into()))?;
        let retained = host
            .writer()
            .retained_operation(run_id)
            .await?
            .ok_or_else(|| {
                AgentdError::Protocol("Desktop Objective has no original operation".into())
            })?;
        let operation = match retained.topic.as_str() {
            codex_hepta_memory::NOTES_REPLACE_TOPIC_V1 => {
                codex_hepta_memory::notes_operation_intent(
                    &config.notes,
                    &retained.payload_json,
                    retained.operation.subject_id().clone(),
                    retained.operation.policy_generation(),
                )
            }
            codex_hepta_memory::CALCULATOR_EVALUATE_TOPIC_V1 => {
                codex_hepta_memory::calculator_operation_intent(
                    &config.calculator,
                    &retained.payload_json,
                    retained.operation.subject_id().clone(),
                    retained.operation.policy_generation(),
                )
            }
            _ => {
                return Err(AgentdError::Protocol(
                    "Desktop operation topic is not registered".into(),
                ));
            }
        }
        .map_err(AgentdError::Invalid)?;
        if operation != retained.operation
            || operation.operation_id().as_str() != run_id
            || operation.semantic_digest() != source_digest
        {
            return Err(AgentdError::Protocol(
                "Desktop Objective differs from its original operation".into(),
            ));
        }
        Ok(retained)
    }
    pub(crate) async fn execute_desktop_objective(
        &self,
        record: &RunStartRecordV1,
    ) -> Result<(), AgentdError> {
        let Some(config) = self.desktop_objective.get() else {
            return Ok(());
        };
        if record.disposition != RunStartObjectiveDispositionV1::Compiled
            || record.admission.profile_digest != config.profile_digest
        {
            return Ok(());
        }
        let run_id = record.snapshot.run_id.as_str();
        let current = self.runs.lock().map_err(poisoned_state)?.run(run_id);
        let Some(current) = current else {
            return Ok(());
        };
        if current.terminal_observed {
            return Ok(());
        }
        let host = self.production_operations.get().ok_or_else(|| {
            AgentdError::Protocol("Desktop operation owner is unavailable".into())
        })?;
        let writer = host.writer();
        let retained = self
            .checked_desktop_operation(config, run_id, record.admission.supplied_source_digest)
            .await?;
        let operation = retained.operation;
        let destination = operation.destination_id().as_str().to_owned();
        // Refresh Fleet/trust outside the run mutex: a newly observed drain
        // itself acquires that mutex to cancel pre-dispatch runs. Bind this
        // validation to the exact phase/revision, then re-read them under the
        // mutation lock. Already dispatched/unknown runs need only readback,
        // including after their original admission authentication expires.
        let candidate = self
            .runs
            .lock()
            .map_err(poisoned_state)?
            .run(run_id)
            .ok_or_else(|| AgentdError::Protocol("Desktop run disappeared".into()))?;
        let dispatch_stamp = if matches!(
            candidate.phase,
            RunPhase::Admitted | RunPhase::ContextAttached
        ) {
            Some((
                candidate.revision,
                candidate.phase,
                self.require_current_run_start(record)?,
            ))
        } else {
            None
        };
        // Only this coordinator's first transition may enter dispatch. The
        // original durable operation then fences the actual effect boundary.
        let first_dispatch = {
            let mut runs = self.runs.lock().map_err(poisoned_state)?;
            let current = runs
                .run(run_id)
                .ok_or_else(|| AgentdError::Protocol("Desktop run disappeared".into()))?;
            if matches!(
                current.phase,
                RunPhase::Admitted | RunPhase::ContextAttached
            ) {
                let Some((revision, phase, now_ms)) = dispatch_stamp else {
                    return Ok(());
                };
                if current.revision != revision || current.phase != phase {
                    return Ok(());
                }
                let context = Digest32::of_bytes(
                    format!(
                        "hepta.desktop.context.v1:{}:{}",
                        record.snapshot.run_id,
                        operation.semantic_digest()
                    )
                    .as_bytes(),
                );
                let attached = runs
                    .attach_context(
                        now_ms,
                        current.revision,
                        ContextAttachment {
                            run_id: run_id.to_string(),
                            request_digest: record.admission.admitted_source_digest.to_string(),
                            objective_digest: record.snapshot.objective_digest.to_string(),
                            body_digest: record.runtime_body_digest.to_string(),
                            artifact_set_digest: record.snapshot.artifact_set_digest.to_string(),
                            authority_epoch: record.snapshot.authority_epoch,
                            generation: record.snapshot.generation,
                            fence_digest: record.snapshot.fence_digest.to_string(),
                            deadline_ms: record.admission.deadline_unix_micros.div_ceil(1_000),
                            context_digest: context.to_string(),
                            compilation_receipt_digest: record
                                .objective_function_v1_digest
                                .to_string(),
                        },
                    )
                    .map_err(run_error)?;
                !runs
                    .mark_dispatched(now_ms, run_id, attached.revision)
                    .map_err(run_error)?
                    .idempotent
            } else {
                false
            }
        };
        if first_dispatch && retained.state == LocalOutcomeState::Queued {
            self.require_current_run_start(record)?;
            let queued = writer
                .prepare_operation(operation, &retained.topic, retained.payload_json)
                .await?;
            // A lost grant/effect/ACK remains owned by the original operation.
            // Never turn an error into a second effect attempt.
            let _ = host
                .dispatch_to_with_grant_provider(&destination, queued)
                .await;
        } else if retained.state == LocalOutcomeState::Indeterminate {
            host.reconcile_for_destination(&destination, /*limit*/ 1)
                .await?;
        }
        let state = writer.status(run_id).await?;
        let mut runs = self.runs.lock().map_err(poisoned_state)?;
        let current = runs
            .run(run_id)
            .ok_or_else(|| AgentdError::Protocol("Desktop run disappeared".into()))?;
        if current.terminal_observed {
            return Ok(());
        }
        let (phase, observed) = match state {
            LocalOutcomeState::Committed => (RunPhase::Succeeded, true),
            LocalOutcomeState::Rejected | LocalOutcomeState::RolledBack => (RunPhase::Failed, true),
            LocalOutcomeState::Queued | LocalOutcomeState::Indeterminate => {
                (RunPhase::Indeterminate, false)
            }
        };
        runs.observe_terminal(run_id, current.revision, phase, observed)
            .map_err(run_error)?;
        Ok(())
    }
}

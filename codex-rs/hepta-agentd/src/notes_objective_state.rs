//! One finite Objective action bound to the original Notes operation owner.
use super::*;
use crate::ContextAttachment;
use crate::RunPhase;
use codex_hepta_learning_ledger::RunStartObjectiveDispositionV1;
use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_memory::NOTES_REPLACE_TOPIC_V1;
use codex_hepta_memory::NotesTargetIdentity;
use codex_hepta_memory::ProductionRetainedOperation;
use codex_hepta_memory::notes_operation_intent;

/// Explicit deployment registration. The profile digest freezes the literal
/// Notes compiler, and the target identifies the actual attached application.
#[derive(Clone, Debug)]
pub struct AgentdNotesObjectiveConfig {
    pub profile_digest: Digest32,
    pub target: NotesTargetIdentity,
}

impl AgentdNotesObjectiveConfig {
    pub(crate) fn validate(&self) -> Result<(), AgentdError> {
        if self.profile_digest.is_zero() {
            return Err(AgentdError::Invalid("Notes profile digest is zero".into()));
        }
        self.target.validate().map_err(AgentdError::Invalid)
    }

    pub(crate) fn validate_host(
        &self,
        host: &crate::AgentdProductionWriterHost,
    ) -> Result<(), AgentdError> {
        self.validate()?;
        if !host.has_destination(&self.target.destination_id()) {
            return Err(AgentdError::Invalid(
                "Notes Objective requires its fixed Notes destination and original grant provider"
                    .into(),
            ));
        }
        Ok(())
    }
}

impl AgentdState {
    pub(crate) async fn validate_notes_source(
        &self,
        profile_digest: Digest32,
        run_id: &str,
        source_digest: Digest32,
    ) -> Result<(), AgentdError> {
        if let Some(config) = self.notes_objective.get() {
            if config.profile_digest != profile_digest {
                return Err(AgentdError::Invalid(
                    "Notes profile differs from registered Objective profile".into(),
                ));
            }
            self.checked_notes_operation(config, run_id, source_digest)
                .await?;
        }
        Ok(())
    }

    async fn checked_notes_operation(
        &self,
        config: &AgentdNotesObjectiveConfig,
        run_id: &str,
        source_digest: Digest32,
    ) -> Result<ProductionRetainedOperation, AgentdError> {
        let host = self
            .production_operations
            .get()
            .ok_or_else(|| AgentdError::Protocol("Notes operation owner is unavailable".into()))?;
        let retained = host
            .writer()
            .retained_operation(run_id)
            .await?
            .ok_or_else(|| {
                AgentdError::Protocol("Notes Objective has no original operation".into())
            })?;
        let operation = notes_operation_intent(
            &config.target,
            &retained.payload_json,
            retained.operation.subject_id().clone(),
            retained.operation.policy_generation(),
        )
        .map_err(AgentdError::Invalid)?;
        if retained.topic != NOTES_REPLACE_TOPIC_V1
            || operation != retained.operation
            || operation.operation_id().as_str() != run_id
            || operation.semantic_digest() != source_digest
        {
            return Err(AgentdError::Protocol(
                "Notes Objective differs from its original operation".into(),
            ));
        }
        Ok(retained)
    }

    pub(crate) async fn execute_notes_objective(
        &self,
        record: &RunStartRecordV1,
    ) -> Result<(), AgentdError> {
        let Some(config) = self.notes_objective.get() else {
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
        let host = self
            .production_operations
            .get()
            .ok_or_else(|| AgentdError::Protocol("Notes operation owner is unavailable".into()))?;
        let writer = host.writer();
        let retained = self
            .checked_notes_operation(config, run_id, record.admission.supplied_source_digest)
            .await?;
        let operation = retained.operation;
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
            .ok_or_else(|| AgentdError::Protocol("Notes run disappeared".into()))?;
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
                .ok_or_else(|| AgentdError::Protocol("Notes run disappeared".into()))?;
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
                        "hepta.notes.context.v1:{}:{}",
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
                .prepare_operation(operation, NOTES_REPLACE_TOPIC_V1, retained.payload_json)
                .await?;
            // A lost grant/effect/ACK remains owned by the original operation.
            // Never turn an error into a second effect attempt.
            let _ = host
                .dispatch_to_with_grant_provider(&config.target.destination_id(), queued)
                .await;
        } else if retained.state == LocalOutcomeState::Indeterminate {
            host.reconcile_for_destination(&config.target.destination_id(), /*limit*/ 1)
                .await?;
        }
        let state = writer.status(run_id).await?;
        let mut runs = self.runs.lock().map_err(poisoned_state)?;
        let current = runs
            .run(run_id)
            .ok_or_else(|| AgentdError::Protocol("Notes run disappeared".into()))?;
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

#[cfg(all(test, target_os = "linux"))]
#[path = "notes_objective_lock_tests.rs"]
mod lock_tests;

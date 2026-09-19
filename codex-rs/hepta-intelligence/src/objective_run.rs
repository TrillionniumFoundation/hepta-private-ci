//! Product composition boundary for authenticated objective compilation and
//! destination-owner run-start publication.
//!
//! The intelligence facade never opens or owns the durable file. It invokes the
//! sealed learning-ledger owner port only after objective admission and
//! deterministic compilation have completed. A successful return therefore
//! proves that the immutable run-start snapshot was durably appended; it grants
//! no effect, model, tool, provider, activation, promotion or release authority.

use std::error::Error;
use std::fmt;

use codex_hepta_learning_ledger::RunStartAdmissionBindingV1;
use codex_hepta_learning_ledger::RunStartAppendReceipt;
use codex_hepta_learning_ledger::RunStartAuthenticationV1;
use codex_hepta_learning_ledger::RunStartJournal;
use codex_hepta_learning_ledger::RunStartObjectiveDispositionV1;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_learning_ledger::RunStartSnapshotV1;
use codex_hepta_learning_ledger::RunStartStoreError;
use codex_hepta_objective::CompileDisposition;
use codex_hepta_objective::ObjectiveAdmissionContextV1;
use codex_hepta_objective::ObjectiveAdmissionError;
use codex_hepta_objective::ObjectiveAdmissionProfileV1;
use codex_hepta_objective::ObjectiveAdmissionReceiptV1;
use codex_hepta_objective::ObjectiveCompileReceipt;
use codex_hepta_objective::ObjectiveConflictReceipt;
use codex_hepta_objective::ObjectiveSourceEnvelopeV1;
use codex_hepta_objective::admit_objective_v1;
use codex_hepta_objective::canonical_native_objective_semantic_bytes_v1;
use codex_hepta_objective::compile_admitted_objective_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveRunBindingsV1 {
    pub authentication: RunStartAuthenticationV1,
    pub run_id: StableId,
    pub runtime_body_digest: Digest32,
    pub preference_state_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub prompt_registry_digest: Digest32,
    pub artifact_set_digest: Digest32,
    pub authority_epoch: u64,
    pub generation: u64,
    pub fence_digest: Digest32,
    /// Exact predecessor retained by the caller for idempotent replay.
    pub expected_run_start_head: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PublishedObjectiveRunV1 {
    pub admission: ObjectiveAdmissionReceiptV1,
    pub objective: ObjectiveCompileReceipt,
    pub run_start: RunStartSnapshotV1,
    pub publication: RunStartAppendReceipt,
    pub authority: AuthorityPosture,
}

#[derive(Debug)]
pub enum ObjectiveRunError {
    Admission(ObjectiveAdmissionError),
    Conflict(ObjectiveConflictReceipt),
    DeadlineMissing,
    RunStart(RunStartStoreError),
}

impl fmt::Display for ObjectiveRunError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl Error for ObjectiveRunError {}
impl From<ObjectiveAdmissionError> for ObjectiveRunError {
    fn from(error: ObjectiveAdmissionError) -> Self {
        Self::Admission(error)
    }
}
impl From<RunStartStoreError> for ObjectiveRunError {
    fn from(error: RunStartStoreError) -> Self {
        Self::RunStart(error)
    }
}

/// Authenticate, compile and durably publish one immutable objective/run-start
/// pair through the destination owner's sealed journal.
///
/// An `ExplicitAbstain` objective is still a valid immutable run start. Runtime
/// consumers may terminate immediately, but the objective is not discarded or
/// silently replaced by a different goal.
pub fn compile_and_publish_objective_run_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
    bindings: ObjectiveRunBindingsV1,
    journal: &mut dyn RunStartJournal,
) -> Result<PublishedObjectiveRunV1, ObjectiveRunError> {
    let admitted = admit_objective_v1(envelope, profile, context)?;
    let outcome = compile_admitted_objective_v1(admitted)?;
    let objective = outcome.compile_result.map_err(ObjectiveRunError::Conflict)?;
    let deadline_unix_micros = outcome
        .receipt
        .deadline_unix_micros
        .ok_or(ObjectiveRunError::DeadlineMissing)?;
    let objective_semantic_bytes =
        canonical_native_objective_semantic_bytes_v1(&objective.objective);
    if Digest32::of_bytes(&objective_semantic_bytes) != objective.objective.semantic_digest {
        return Err(ObjectiveRunError::RunStart(
            RunStartStoreError::ObjectiveDigestMismatch,
        ));
    }
    let run_start = RunStartSnapshotV1 {
        run_id: bindings.run_id,
        objective_digest: objective.objective.semantic_digest,
        hard_constraint_digest: objective.objective.hard_constraint_digest,
        preference_state_digest: bindings.preference_state_digest,
        model_tuple_digest: bindings.model_tuple_digest,
        prompt_registry_digest: bindings.prompt_registry_digest,
        artifact_set_digest: bindings.artifact_set_digest,
        authority_epoch: bindings.authority_epoch,
        generation: bindings.generation,
        fence_digest: bindings.fence_digest,
    };
    let disposition = match objective.disposition {
        CompileDisposition::Compiled => RunStartObjectiveDispositionV1::Compiled,
        CompileDisposition::ExplicitAbstain => RunStartObjectiveDispositionV1::ExplicitAbstain,
    };
    let publication = journal.append_run_start(
        bindings.expected_run_start_head,
        RunStartRecordV1 {
            authentication: bindings.authentication,
            admission: RunStartAdmissionBindingV1 {
                profile_digest: outcome.receipt.profile_digest,
                intent_digest: outcome.receipt.intent_digest,
                admitted_source_digest: outcome.receipt.admitted_source_digest,
                observed_at_unix_micros: outcome.receipt.observed_at_unix_micros,
                deadline_unix_micros,
            },
            disposition,
            snapshot: run_start.clone(),
            runtime_body_digest: bindings.runtime_body_digest,
            objective_semantic_bytes,
        },
    )?;
    debug_assert!(matches!(
        objective.disposition,
        CompileDisposition::Compiled | CompileDisposition::ExplicitAbstain
    ));
    Ok(PublishedObjectiveRunV1 {
        admission: outcome.receipt,
        objective,
        run_start,
        publication,
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
#[path = "objective_run_tests.rs"]
mod tests;
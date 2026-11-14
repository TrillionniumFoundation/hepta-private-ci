//! Owner-local, read-only Objective observations. These are not durable leases.

use std::sync::Arc;
use std::sync::Weak;

use codex_hepta_learning_ledger::RunStartObjectiveDispositionV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::AgentdState;
use super::poisoned_state;
use crate::AgentdError;
use crate::RunPhase;
use crate::RunSnapshot;
use crate::authbus_trust::invalid;
use crate::objective_runtime::ObjectiveRuntimeHost;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct CurrentObjectiveSnapshotV1 {
    pub(crate) subject_id: StableId,
    pub(crate) run_id: StableId,
    pub(crate) objective_digest: Digest32,
    pub(crate) run_revision: u64,
    pub(crate) run_incarnation: u64,
    pub(crate) phase: RunPhase,
    pub(crate) authority_epoch: u64,
    pub(crate) fleet_generation: u64,
    pub(crate) fence_digest: Digest32,
    pub(crate) deadline_ms: u64,
}

/// An observation made by the attached owner, bound to its in-process identity.
/// Freshness must be checked again at use. No serialization or constructor is
/// exposed; a digest alone cannot restore this proof after process restart.
#[derive(Clone, Debug)]
pub(crate) struct CurrentObjectiveReadV1 {
    snapshot: CurrentObjectiveSnapshotV1,
    binding_digest: Digest32,
    owner: Weak<ObjectiveRuntimeHost>,
}

impl CurrentObjectiveReadV1 {
    pub(crate) fn snapshot(&self) -> &CurrentObjectiveSnapshotV1 {
        &self.snapshot
    }

    pub(crate) fn binding_digest(&self) -> Digest32 {
        self.binding_digest
    }
}

impl AgentdState {
    pub(crate) fn checked_current_objective(
        &self,
        run_id: &str,
    ) -> Result<CurrentObjectiveReadV1, AgentdError> {
        let run_id = StableId::new(run_id).map_err(|error| invalid(&error.to_string()))?;
        let host = self
            .objective_runtime
            .get()
            .ok_or_else(|| invalid("no attached Objective owner"))?;
        host.with_run_start(&run_id, |record, _journal_head| {
            if record.disposition != RunStartObjectiveDispositionV1::Compiled
                || record.admission.authority.grants_any()
                || record.objective_function_v1_digest.is_zero()
                || record.objective_function_v1_bytes.is_empty()
            {
                return Err(invalid("durable objective is not a compiled read context"));
            }
            self.require_current_run_start(record)?;
            let before = self
                .runs
                .lock()
                .map_err(poisoned_state)?
                .run_observation(run_id.as_str())
                .ok_or_else(|| invalid("objective run is not admitted"))?;
            // Never refresh Fleet while holding runs: draining refresh takes
            // that lock too. Re-observe lifecycle after the authority refresh.
            let now_ms = self.require_current_run_start(record)?;
            let runs = self.runs.lock().map_err(poisoned_state)?;
            if runs.run_observation(run_id.as_str()).as_ref() != Some(&before) {
                return Err(invalid("objective run changed during current read"));
            }
            let (runtime_snapshot, incarnation, receipt) = before;
            let deadline_ms = record
                .admission
                .deadline_unix_micros
                .checked_add(999)
                .ok_or_else(|| invalid("objective deadline overflow"))?
                / 1_000;
            let expected = RunSnapshot {
                run_id: run_id.to_string(),
                request_digest: record.admission.admitted_source_digest.to_string(),
                objective_digest: record.snapshot.objective_digest.to_string(),
                body_digest: record.runtime_body_digest.to_string(),
                artifact_set_digest: record.snapshot.artifact_set_digest.to_string(),
                authority_epoch: record.snapshot.authority_epoch,
                generation: record.snapshot.generation,
                fence_digest: record.snapshot.fence_digest.to_string(),
                deadline_ms,
            };
            if runtime_snapshot != expected || receipt.revision == 0 || deadline_ms <= now_ms {
                return Err(invalid(
                    "objective run is expired, inactive or has mixed identity",
                ));
            }
            let phase = match receipt.phase {
                RunPhase::Admitted => 1,
                RunPhase::ContextAttached => 2,
                RunPhase::Dispatched => 3,
                RunPhase::Cancelling
                | RunPhase::Cancelled
                | RunPhase::Succeeded
                | RunPhase::Failed
                | RunPhase::Indeterminate => return Err(invalid("objective run is inactive")),
            };
            let snapshot = CurrentObjectiveSnapshotV1 {
                subject_id: StableId::new(self.identity.agent_id.as_str())
                    .map_err(|error| invalid(&error.to_string()))?,
                run_id: run_id.clone(),
                objective_digest: record.snapshot.objective_digest,
                run_revision: receipt.revision,
                run_incarnation: incarnation,
                phase: receipt.phase,
                authority_epoch: record.snapshot.authority_epoch,
                fleet_generation: record.snapshot.generation,
                fence_digest: record.snapshot.fence_digest,
                deadline_ms,
            };
            // Fixed-order, bounded scalars/digests only. Observation time is
            // deliberately absent, so an unchanged current read is comparable.
            let material = serde_json::json!([
                "hepta.agentd.current-objective.v1",
                snapshot.subject_id.as_str(),
                snapshot.run_id.as_str(),
                self.identity.spawn_generation,
                record.admission.profile_id.as_str(),
                record.admission.profile_revision,
                record.admission.profile_digest.to_string(),
                record.authentication.issuer_id.as_str(),
                record.authentication.key_epoch,
                record.authentication.message_id.as_str(),
                record.authentication.sequence,
                record.authentication.scope_digest.to_string(),
                Digest32::of_bytes(&record.authentication.signature).to_string(),
                record.authentication.signed_body_digest.to_string(),
                record.authentication.expires_at_ms,
                snapshot.objective_digest.to_string(),
                record.objective_function_v1_digest.to_string(),
                record.admission.supplied_source_digest.to_string(),
                record.admission.intent_digest.to_string(),
                record.admission.admitted_source_digest.to_string(),
                record.runtime_body_digest.to_string(),
                record.admission.observed_at_unix_micros,
                record.admission.deadline_unix_micros,
                record.snapshot.hard_constraint_digest.to_string(),
                record.snapshot.preference_state_digest.to_string(),
                record.snapshot.model_tuple_digest.to_string(),
                record.snapshot.prompt_registry_digest.to_string(),
                record.snapshot.artifact_set_digest.to_string(),
                snapshot.authority_epoch,
                snapshot.fleet_generation,
                snapshot.fence_digest.to_string(),
                deadline_ms,
                incarnation,
                receipt.revision,
                phase,
                receipt.context_digest,
                receipt.compilation_receipt_digest
            ]);
            Ok(CurrentObjectiveReadV1 {
                snapshot,
                binding_digest: Digest32::of_bytes(&serde_json::to_vec(&material)?),
                owner: Arc::downgrade(host),
            })
        })
    }

    pub(crate) fn revalidate_current_objective(
        &self,
        observed: &CurrentObjectiveReadV1,
    ) -> Result<(), AgentdError> {
        let current = self.checked_current_objective(observed.snapshot.run_id.as_str())?;
        if !Weak::ptr_eq(&current.owner, &observed.owner)
            || current.snapshot != observed.snapshot
            || current.binding_digest != observed.binding_digest
        {
            return Err(invalid("current Objective observation no longer matches"));
        }
        Ok(())
    }
}

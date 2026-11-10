//! Read-only Objective/Circuit provenance before the first Root learning claim.
//! These independent owner reads do not form a transaction or grant dataset,
//! training, signing, selection or external-effect authority. Historical claimed
//! operations still reconcile through their original stage owners.

use codex_hepta_learning_artifacts::LearningIterationRequestV1;
use codex_hepta_learning_ledger::RunStartPublication;

use super::*;

impl AgentdState {
    pub(crate) async fn require_circuit_learning_source(
        &self,
        request: &LearningIterationRequestV1,
    ) -> Result<(), AgentdError> {
        if request.agent_id.as_str() != self.identity().agent_id.as_str()
            || self.circuit_learning_source() != Some(&request.source_run_id)
        {
            return Err(invalid(
                "learning source differs from the original daemon scope",
            ));
        }
        let host = self
            .objective_runtime
            .get()
            .ok_or_else(|| invalid("original learning Objective owner is unavailable"))?;
        let original = host.learning_source_record(request)?;
        self.require_learning_source_authentication(&original.0)?;
        let store = self.circuit_task_store()?;
        let delivery = store
            .circuit_learning_delivery(request.source_run_id.as_str())
            .await
            .map_err(|error| invalid(&format!("learning source outbox: {error:?}")))?
            .ok_or_else(|| invalid("original learning completion intent is unavailable"))?;
        let intent = &delivery.intent;
        if intent.source_run_id != request.source_run_id.as_str()
            || intent.operation_id != request.operation_id.as_str()
            || intent.completed_task_receipt.as_str() != request.completed_task_receipt.to_string()
            || intent.objective_digest.as_str() != request.envelope.objective_digest.to_string()
        {
            return Err(invalid(
                "learning source request differs from original completion",
            ));
        }
        let trace = store
            .bounded_circuit_committed_trace(request.source_run_id.as_str())
            .await
            .map_err(|error| invalid(&format!("learning source Circuit history: {error}")))?
            .ok_or_else(|| invalid("original learning Circuit history is unavailable"))?;
        if trace.run().run_id() != request.source_run_id.as_str()
            || trace.history_digest() != &intent.completed_task_receipt
            || trace.run().outcome().is_none()
            || trace.run().unresolved() != 0
        {
            return Err(invalid("learning source Circuit completion differs"));
        }
        // Re-read the original owner views after async reads. No lock crosses
        // an await, and a caller-supplied record or outbox row is never trusted.
        let current = store
            .circuit_learning_delivery(request.source_run_id.as_str())
            .await
            .map_err(|error| invalid(&format!("learning source outbox recheck: {error:?}")))?
            .ok_or_else(|| invalid("original learning completion disappeared"))?;
        if current.intent != delivery.intent || host.learning_source_record(request)? != original {
            return Err(invalid(
                "original learning source changed during resolution",
            ));
        }
        // Today's daemon admission, original issuer/key and revocation remain
        // required. This historical signature check never admits the old task.
        self.require_learning_source_authentication(&original.0)?;
        Ok(())
    }

    fn require_learning_source_authentication(
        &self,
        record: &RunStartRecordV1,
    ) -> Result<(), AgentdError> {
        authbus_ingress::require_objective_ready(self)?;
        let trust = authbus_ingress::attached(self)?.trust(self)?;
        authenticate_learning_source_at(record, &trust, self.identity(), authbus_ingress::now_ms()?)
    }
}

fn authenticate_learning_source_at(
    record: &RunStartRecordV1,
    trust: &TextTrust,
    identity: &AgentdIdentity,
    now_ms: u64,
) -> Result<(), AgentdError> {
    // The admission timestamp belongs to the original immutable journal, not
    // the new learning request. Expiry prevents new effects, not provenance.
    let admitted_ms = record.admission.observed_at_unix_micros / 1_000;
    if admitted_ms > now_ms || !authentication_is_current(record, trust, identity, admitted_ms)? {
        return Err(invalid(
            "original learning Objective authentication is unavailable",
        ));
    }
    Ok(())
}

impl ObjectiveRuntimeHost {
    fn learning_source_record(
        &self,
        request: &LearningIterationRequestV1,
    ) -> Result<(RunStartRecordV1, RunStartPublication), AgentdError> {
        let state = self
            .state
            .lock()
            .map_err(|_| invalid("learning source Objective journal is unavailable"))?;
        let record = state
            .journal
            .get(&request.source_run_id)
            .map_err(store_error)?
            .ok_or_else(|| invalid("original learning Objective publication is unavailable"))?;
        let publication = state
            .journal
            .publication(&request.source_run_id)
            .map_err(store_error)?
            .ok_or_else(|| {
                invalid("original learning Objective publication metadata is unavailable")
            })?;
        if record.disposition != RunStartObjectiveDispositionV1::Compiled
            || record.admission.profile_digest != self.profile_digest
            || record.snapshot.run_id != request.source_run_id
            || record.snapshot.objective_digest != request.envelope.objective_digest
        {
            return Err(invalid(
                "learning source differs from the original Objective",
            ));
        }
        Ok((record.clone(), publication))
    }
}

#[cfg(test)]
#[path = "objective_learning_source_auth_tests.rs"]
mod tests;

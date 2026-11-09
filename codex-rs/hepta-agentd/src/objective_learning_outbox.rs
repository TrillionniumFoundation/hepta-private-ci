//! Recover historical completion pointers without renewing an Objective or
//! granting training authority. Current source authority is checked at delivery.

use codex_hepta_automation::AutomationStore;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::StableId;

use super::*;

impl ObjectiveRuntimeHost {
    pub(crate) async fn reconcile_learning_outbox(
        &self,
        store: &AutomationStore,
        source_run_id: Option<&StableId>,
    ) -> Result<(), AgentdError> {
        let Some(source_run_id) = source_run_id else {
            return Ok(());
        };
        let sources = {
            let state = self
                .state
                .lock()
                .map_err(|_| invalid("objective journal lock is poisoned"))?;
            state
                .journal
                .records()
                .map_err(store_error)?
                .into_iter()
                .filter(|record| {
                    record.disposition == RunStartObjectiveDispositionV1::Compiled
                        && record.snapshot.run_id.as_str() == source_run_id.as_str()
                })
                .map(|record| {
                    (
                        record.snapshot.run_id.to_string(),
                        record.snapshot.objective_digest,
                    )
                })
                .collect::<Vec<_>>()
        };
        // The journal bounds the scan to MAX_RUN_START_RECORDS; only the
        // configured source can enqueue. No new task or grant is executed.
        for (run_id, objective) in sources {
            let Some(trace) = store
                .bounded_circuit_committed_trace(&run_id)
                .await
                .map_err(|error| invalid(&format!("Circuit completion recovery: {error}")))?
            else {
                continue;
            };
            if trace.run().outcome().is_none() || trace.run().unresolved() != 0 {
                continue;
            }
            let objective = Sha256Digest::parse(objective.to_string())
                .map_err(|error| invalid(&format!("Circuit completion objective: {error}")))?;
            store
                .enqueue_circuit_learning(&trace, objective)
                .await
                .map_err(|error| {
                    invalid(&format!("Circuit learning outbox recovery: {error:?}"))
                })?;
        }
        Ok(())
    }
}

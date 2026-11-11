//! Recover historical completion pointers without renewing an Objective or
//! granting training authority. Current source authority is checked at delivery.

use codex_hepta_automation::AutomationStore;
use codex_hepta_types::StableId;

use super::*;

impl ObjectiveRuntimeHost {
    pub(crate) async fn reconcile_learning_outbox(
        &self,
        store: &AutomationStore,
        source_run_id: Option<&StableId>,
        original_state: &crate::AgentdState,
    ) -> Result<(), AgentdError> {
        let Some(source_run_id) = source_run_id else {
            return Ok(());
        };
        if original_state.circuit_learning_origin(source_run_id).is_none() {
            return Err(invalid("original learning source profile is unavailable"));
        }
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
                .collect::<Vec<_>>()
        };
        // The journal bounds the scan to MAX_RUN_START_RECORDS; only the
        // configured source can enqueue. No new task or grant is executed.
        for record in sources {
            let run_id = record.snapshot.run_id.as_str();
            let Some(trace) = store
                .bounded_circuit_committed_trace(run_id)
                .await
                .map_err(|error| invalid(&format!("Circuit completion recovery: {error}")))?
            else {
                continue;
            };
            if trace.run().outcome().is_none() || trace.run().unresolved() != 0 {
                continue;
            }
            let readiness = original_state.observe_circuit_learning(&record, &trace).await;
            original_state
                .enqueue_original_circuit_learning(&record, &trace, readiness)
                .await?;
        }
        Ok(())
    }
}

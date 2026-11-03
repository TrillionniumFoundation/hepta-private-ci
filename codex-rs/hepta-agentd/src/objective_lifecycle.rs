//! Access to the same original Objective journal for lifecycle composition.

use super::*;
use codex_hepta_learning_ledger::RunStartAppendReceipt;

impl ObjectiveRuntimeHost {
    /// A stopped run may reconcile only its exact already authenticated
    /// queued input. It cannot compile, restore owners, append a publication,
    /// or authorize a missing queue row. The original stop facts stay intact.
    pub(crate) fn observe_stopped_queue_replay(&self, authentication: &RunStartAuthenticationV1,
        run_id: &StableId, payload: &[u8]) -> Result<Option<(RunStartRecordV1, RunStartAppendReceipt)>, AgentdError> {
        let state = self.state.lock().map_err(|_| invalid("original Objective journal lock poisoned"))?;
        if state.journal.cancellation(run_id).map_err(store_error)?.is_none()
            && state.journal.closed(run_id).map_err(store_error)?.is_none() {
            return Ok(None);
        }
        let original = state.journal.get(run_id).map_err(store_error)?
            .ok_or_else(|| invalid("stopped original run has no immutable publication"))?;
        if original.authentication != *authentication
            || original.authenticated_payload.as_deref() != Some(payload)
            || original.disposition != RunStartObjectiveDispositionV1::Compiled {
            return Err(AgentdError::GenerationFenced(
                "stopped original run permits only its exact signed queued observation".to_owned()));
        }
        let prepared = state.journal.prepared(run_id).map_err(store_error)?
            .ok_or_else(|| invalid("original canonical preparation is not durable; outcome remains unknown"))?;
        if prepared.original() != original {
            return Err(invalid("stopped original preparation differs from its publication"));
        }
        let publication = state.journal.observe_run_start_receipt(run_id).map_err(store_error)?
            .ok_or_else(|| invalid("stopped original run has no publication receipt"))?;
        Ok(Some((original.clone(), publication)))
    }

    pub(crate) fn with_run_journal<T>(&self,
        action: impl FnOnce(&mut DurableRunStartJournal) -> Result<T, AgentdError>) -> Result<T, AgentdError> {
        let mut state = self.state.lock().map_err(|_| invalid("original Objective journal lock poisoned"))?;
        action(&mut state.journal)
    }
}

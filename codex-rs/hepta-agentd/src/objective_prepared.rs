//! Completed canonical handoffs owned by the existing Objective run journal.
//! Nothing in this module claims a queue row, creates a turn or dispatches work.

use super::*;
use codex_hepta_learning_ledger::CommittedRunPreparedV1;
use crate::{NativeContextMaterialV1, PreparedAgentdIntelligenceRunV1};

impl ObjectiveRuntimeHost {
    pub(crate) fn publish_prepared_handoff(&self, agentd: &AgentdState, original: &RunStartRecordV1,
        prepared: &PreparedAgentdIntelligenceRunV1, materials: Vec<NativeContextMaterialV1>) -> Result<(), AgentdError> {
        agentd.require_current_run_start(original)?;
        let attached = agentd.native_run_receipt(original.snapshot.run_id.as_str())?;
        let mut state = self.state.lock().map_err(|_| invalid("original Objective journal lock poisoned"))?;
        if state.journal.get(&original.snapshot.run_id).map_err(store_error)? != Some(original) {
            return Err(invalid("prepared publication differs from original Objective journal"));
        }
        let digest = state.journal.run_start_record_digest(&original.snapshot.run_id).map_err(store_error)?
            .ok_or_else(|| invalid("prepared publication has no original RunStart"))?;
        let record = prepared.prepared_record(digest, &attached, materials)
            .map_err(|error| invalid(&format!("original canonical prepared publication: {error:#}")))?;
        if record.run_id != original.snapshot.run_id {
            return Err(invalid("prepared publication belongs to another run"));
        }
        let predecessor = state.journal.head_digest();
        state.journal.append_prepared(predecessor, record).map_err(store_error)?;
        drop(state);
        agentd.require_current_run_start(original)?;
        Ok(())
    }

    pub(crate) fn committed_prepared(&self, run_id: &str) -> Result<Option<CommittedRunPreparedV1>, AgentdError> {
        let run_id = StableId::new(run_id).map_err(|error| invalid(&format!("prepared run identity: {error}")))?;
        let state = self.state.lock().map_err(|_| invalid("original Objective journal lock poisoned"))?;
        crate::state::run_lifecycle::require_fresh(Some(&state.journal), run_id.as_str())?;
        state.journal.prepared(&run_id).map_err(store_error)
    }

    /// Read an immutable Prepared audit fact without granting continuation.
    /// Fresh recovery must still use committed_prepared and its original stop
    /// fence; observer access never restores the canonical owner pipeline.
    pub(crate) fn observe_committed_prepared(&self, run_id: &str) -> Result<Option<CommittedRunPreparedV1>, AgentdError> {
        let run_id = StableId::new(run_id).map_err(|error| invalid(&format!("prepared run identity: {error}")))?;
        let state = self.state.lock().map_err(|_| invalid("original Objective journal lock poisoned"))?;
        state.journal.prepared(&run_id).map_err(store_error)
    }

    /// Bounded lookup over the original journal projection, not another route
    /// or input registry. Only the one exact signed input may select a handoff.
    pub(crate) fn committed_prepared_for_queue(&self, identity: &AgentdIdentity,
        thread_id: &str, client_id: &str, payload_sha256: &str) -> Result<Option<CommittedRunPreparedV1>, AgentdError> {
        let state = self.state.lock().map_err(|_| invalid("original Objective journal lock poisoned"))?;
        let mut matched = None;
        for original in state.journal.records().map_err(store_error)? {
            if original.authenticated_payload.is_none() { continue; }
            let derived = crate::canonical_queued_input::queued_client_user_message_id(identity, original)
                .map_err(|error| invalid(&format!("original client correlation: {error:#}")))?;
            if derived != client_id { continue; }
            let queued = crate::canonical_queued_input::queued_input(identity, original)
                .map_err(|error| invalid(&format!("original queued input: {error:#}")))?;
            if matched.is_some() || queued.thread_id != thread_id || queued.input_payload_sha256 != payload_sha256 {
                return Err(invalid("original canonical queue correlation conflicts"));
            }
            matched = Some(original.snapshot.run_id.clone());
        }
        match matched {
            Some(run_id) => {
                crate::state::run_lifecycle::require_fresh(Some(&state.journal), run_id.as_str())?;
                state.journal.prepared(&run_id).map_err(store_error)
            }
            None => Ok(None),
        }
    }
}

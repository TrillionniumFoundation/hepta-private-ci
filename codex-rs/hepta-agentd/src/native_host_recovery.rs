//! Recover the same ThreadStore checkpoint and original effects. Observation
//! remains separate from the sealed same-turn checkpoint continuation path.

use super::*;
use codex_hepta_types::StableId;
use codex_thread_store::{NativeCheckpointCurrentness, NativeCheckpointOpenMode, NativeCheckpointPermit, ThreadStoreError, ThreadStoreFuture};

// This value cannot produce a commit permit. It exists only to open the same
// live ThreadStore's read-only recovery path before restoring the coordinator.
pub(super) struct ReadOriginalOnly;

impl NativeCheckpointCurrentness for ReadOriginalOnly {
    fn acquire<'a>(&'a self, _binding: &'a NativeCheckpointBinding) -> ThreadStoreFuture<'a, NativeCheckpointPermit<'a>> {
        Box::pin(async {
            Err(ThreadStoreError::Conflict { message: "original checkpoint reader cannot authorize a write".to_owned() })
        })
    }
}

impl AgentdNativeHost {
    pub(crate) async fn read_hosted_checkpoint_chain(&self, live: &LiveThread,
        original: &NativeCheckpointBinding)
        -> Result<(Vec<codex_thread_store::StoredNativeCheckpoint>, NativeTurnAnchorV1)> {
        self.host.writer().verify_current_authority().await?;
        ensure!(original.lease_id == self.host.writer().lease_id(), "hosted checkpoint uses another original lease");
        NativeThreadTurnOwner::<NativeProductionAdmission>::read_original_chain(
            live.clone(), original.clone(), Arc::new(ReadOriginalOnly),
        ).await
    }

    pub(crate) async fn read_hosted_checkpoint_record(&self, live: &LiveThread,
        original: &NativeCheckpointBinding)
        -> Result<(codex_thread_store::StoredNativeCheckpoint, NativeTurnAnchorV1, TurnState)> {
        self.host.writer().verify_current_authority().await?;
        ensure!(original.lease_id == self.host.writer().lease_id(), "hosted checkpoint uses another original lease");
        NativeThreadTurnOwner::<NativeProductionAdmission>::read_original_record(
            live.clone(), original.clone(), Arc::new(ReadOriginalOnly),
        ).await
    }

    /// A prepared continuation owns abandonment cleanup before it leaves the
    /// executor hook. Losing Core's caller cannot leave the rearmed run live.
    pub(crate) fn retain_checkpoint_continuation(&self, run: &RunReceipt) -> Result<NativePreparedGuard> {
        let state = self.gate.state()?;
        let active = state.track_native_recovery(&run.run_id)?;
        let guard = NativePreparedGuard { state, run_id: run.run_id.clone(), dispatched_revision: run.revision, _active: active };
        ensure!(guard.state.require_native_effect(&run.run_id)? == *run,
            "original checkpoint continuation lost its dispatched receipt");
        Ok(guard)
    }

    /// Recover the exact original owner; this path never creates or replaces
    /// its first checkpoint. Physical effects still require Core's live entry.
    pub(crate) async fn resume_hosted_checkpoint(&self, live: LiveThread, run: RunReceipt,
        scope: NativeTurnScope, evidence: crate::native_hosted_turn::NativeContinuationEvidence,
        original: NativePreparedGuard) -> Result<NativePreparedTurn> {
        let writer = self.host.writer();
        let anchor = evidence.anchor();
        let execution = anchor.execution.as_ref().context("original checkpoint has no execution scope")?;
        let policy = Generation::new(execution.policy_generation)?;
        let scope_digest = crate::native_admission::execution_scope_digest(&anchor.checkpoint, &run,
            writer.owner_agent_id(), &scope, policy)?;
        evidence.verify_binding(&writer,
            &codex_hepta_contracts::Sha256Digest::parse(scope_digest.to_string()).map_err(anyhow::Error::msg)?)?;
        ensure!(original.run_id == run.run_id && original.dispatched_revision == run.revision
            && Arc::ptr_eq(&original.state, &self.gate.state()?)
            && original.state.require_native_effect(&run.run_id)? == run,
            "checkpoint continuation no longer owns its original live run");
        let admission = self.admission_with_policy(anchor.checkpoint.clone(), scope, policy, &run)?;
        let (expected, expected_anchor) = evidence.release();
        let (owner, turn) = NativeThreadTurnOwner::recover(live, expected_anchor.checkpoint.clone(),
            admission.clone(), admission.clone()).await?;
        ensure!(owner.anchor() == &expected_anchor, "checkpoint continuation changed its original anchor");
        owner.require_checkpoint(&expected)?;
        Ok(NativePreparedTurn { owner, admission, turn, _original: original })
    }

    pub(crate) async fn read_hosted_checkpoint(&self, live: &LiveThread,
        original: &NativeCheckpointBinding) -> Result<(NativeTurnAnchorV1, TurnState)> {
        self.host.writer().verify_current_authority().await?;
        ensure!(original.lease_id == self.host.writer().lease_id(), "hosted checkpoint uses another original lease");
        NativeThreadTurnOwner::<NativeProductionAdmission>::read_original(
            live.clone(), original.clone(), Arc::new(ReadOriginalOnly),
        ).await
    }

    pub(crate) async fn has_hosted_checkpoint(&self, live: &LiveThread,
        original: &NativeCheckpointBinding) -> Result<bool> {
        self.host.writer().verify_current_authority().await?;
        ensure!(original.lease_id == self.host.writer().lease_id(), "hosted checkpoint uses another original lease");
        let session = live.open_native_checkpoint(original.clone(), NativeCheckpointOpenMode::Inspect, Arc::new(ReadOriginalOnly)).await?;
        Ok(matches!(live.load_native_checkpoint(&session).await?, codex_thread_store::NativeCheckpointLoad::Present(_)))
    }

    /// Strong queue admission observation, never a new native dispatch. A live
    /// original run keeps its phase; a missing coordinator is restored only as
    /// Indeterminate. The original ThreadStore owner fsyncs any projection gap.
    pub(crate) async fn confirm_hosted_checkpoint(&self, live: LiveThread,
        anchor: &NativeTurnAnchorV1) -> Result<()> {
        let original = anchor.run.as_ref().context("hosted checkpoint has no original run")?;
        let execution = anchor.execution.as_ref().context("hosted checkpoint has no original scope")?;
        let state = self.gate.state()?;
        let run = match state.native_run_receipt(&original.snapshot.run_id) {
            Ok(run) => {
                ensure!(state.native_run_snapshot(&run.run_id)? == original.snapshot
                    && run.context_digest.as_ref() == Some(&original.context_digest)
                    && run.compilation_receipt_digest.as_ref() == Some(&original.compilation_receipt_digest),
                    "hosted checkpoint conflicts with the original coordinator");
                run
            }
            Err(_) => state.restore_native_run(original.clone())?,
        };
        let scope = NativeTurnScope {
            cell_id: StableId::new(execution.cell_id.clone())?, organ_id: StableId::new(execution.organ_id.clone())?,
            final_scope_id: StableId::new(execution.final_scope_id.clone())?,
        };
        let admission = self.admission_with_policy(anchor.checkpoint.clone(), scope,
            Generation::new(execution.policy_generation)?, &run)?;
        let (owner, _) = NativeThreadTurnOwner::recover(live, anchor.checkpoint.clone(),
            admission.clone(), admission).await?;
        ensure!(owner.anchor() == anchor, "hosted checkpoint changed during admission observation");
        owner.confirm_durable().await
    }

    /// Core already owns recovery of this admitted input and its queue. This
    /// entry observes the saved original effects only; it does not claim or
    /// complete a queue row and cannot reconstruct fresh execution authority.
    pub(crate) async fn recover_hosted_turn(&self, agent: &NativeAgent, live: LiveThread,
        expected: NativeTurnAnchorV1, cancellation: &CancellationToken) -> Result<NativeTurnResult> {
        let (anchor, _) = self.read_hosted_checkpoint(&live, &expected.checkpoint).await?;
        ensure!(anchor == expected, "hosted original checkpoint changed before recovery");
        let original_run = anchor.run.as_ref().context("hosted checkpoint lacks original run")?;
        let execution = anchor.execution.as_ref().context("hosted checkpoint lacks original scope")?;
        let state = self.gate.state()?;
        let observed_success = state.native_run_receipt(&original_run.snapshot.run_id).ok()
            .filter(|run| run.phase == RunPhase::Succeeded && run.terminal_observed);
        let run = if let Some(run) = observed_success {
            ensure!(state.native_run_snapshot(&run.run_id)? == original_run.snapshot
                && run.context_digest.as_ref() == Some(&original_run.context_digest)
                && run.compilation_receipt_digest.as_ref() == Some(&original_run.compilation_receipt_digest),
                "hosted terminal checkpoint conflicts with the original run");
            run
        } else {
            let run = state.restore_native_run(original_run.clone())?;
            ensure!(matches!(run.phase, RunPhase::Indeterminate | RunPhase::Cancelling | RunPhase::Cancelled | RunPhase::Succeeded | RunPhase::Failed), "hosted recovery must remain observation-only");
            run
        };
        let scope = NativeTurnScope {
            cell_id: StableId::new(execution.cell_id.clone())?, organ_id: StableId::new(execution.organ_id.clone())?,
            final_scope_id: StableId::new(execution.final_scope_id.clone())?,
        };
        let admission = self.admission_with_policy(anchor.checkpoint.clone(), scope,
            Generation::new(execution.policy_generation)?, &run)?;
        let (owner, turn) = NativeThreadTurnOwner::recover(live, anchor.checkpoint.clone(),
            admission.clone(), admission.clone()).await?;
        ensure!(owner.anchor() == &anchor, "hosted recovery changed original correlation");
        if let Some(outcome) = settled_original_outcome(&owner, &turn, &run).await? {
            return Ok(NativeTurnResult { outcome, state: turn, run });
        }
        let _active = state.track_native_observation(&run.run_id)?;
        self.drive(agent, owner, admission, turn, cancellation, NativeDriveMode::ObserveOriginal, NativeEntryOwner::Agentd).await
    }

    /// Restore the original checkpoint/history and run. A recovered
    /// Indeterminate run can observe old effects but the entry gate never
    /// converts it into a fresh execution grant.
    pub async fn recover_turn(&self, agent: &NativeAgent, recovery: NativeTurnRecovery, cancellation: &CancellationToken) -> Result<NativeTurnResult> {
        let state = self.gate.state()?;
        self.host.writer().verify_current_authority().await?;
        ensure!(recovery.original.lease_id == self.host.writer().lease_id(), "cold native recovery uses another production lease");
        let (anchor, _) = NativeThreadTurnOwner::<NativeProductionAdmission>::read_original(
            recovery.live_thread.clone(), recovery.original.clone(), Arc::new(ReadOriginalOnly),
        ).await?;
        let original_run = anchor.run.as_ref().context("native checkpoint has no original coordinator recovery; held")?;
        let execution = anchor.execution.as_ref().context("native checkpoint has no original execution scope; held")?;
        ensure!(anchor.queue.is_some() == recovery.queue.is_some(), "cold native recovery requires its exact original QueueStore handle");
        let run = state.restore_native_run(original_run.clone())?;
        ensure!(matches!(run.phase, RunPhase::Indeterminate | RunPhase::Cancelling | RunPhase::Cancelled | RunPhase::Succeeded | RunPhase::Failed), "cold native recovery did not retain observation-only coordinator state");
        let scope = NativeTurnScope {
            cell_id: StableId::new(execution.cell_id.clone())?,
            organ_id: StableId::new(execution.organ_id.clone())?,
            final_scope_id: StableId::new(execution.final_scope_id.clone())?,
        };
        let admission = self.admission_with_policy(recovery.original.clone(), scope, Generation::new(execution.policy_generation)?, &run)?;
        let (owner, turn) = NativeThreadTurnOwner::recover(recovery.live_thread, recovery.original, admission.clone(), admission.clone()).await?;
        ensure!(owner.anchor() == &anchor, "original checkpoint correlation changed during coordinator restoration");
        if let Some(queue) = recovery.queue {
            let now = now_ms()?;
            let expiry = now.checked_add(30_000).context("queue recovery deadline overflow")?;
            let observer_digest = Digest32::of_bytes(&serde_json::to_vec(&(
                self.host.writer().owner_agent_id().as_str(), run.run_id.as_str(),
            ))?);
            let observer_id = format!("native-recovery:{observer_digest}");
            NativeQueueDispatch::reconcile_completed(queue, &owner, observer_id, now, expiry).await?;
        }
        if let Some(outcome) = settled_original_outcome(&owner, &turn, &run).await? {
            return Ok(NativeTurnResult { outcome, state: turn, run });
        }
        let _active = state.track_native_observation(&run.run_id)?;
        self.drive(agent, owner, admission, turn, cancellation, NativeDriveMode::ObserveOriginal, NativeEntryOwner::Agentd).await
    }

}


/// An original terminal decision is not new execution authority. Missing old
/// pending output still goes through the observer; a complete original result
/// can finish Core history without rearming the run or claiming another nonce.
async fn settled_original_outcome(owner: &NativeThreadTurnOwner<NativeProductionAdmission>,
    turn: &TurnState, run: &RunReceipt) -> Result<Option<RunOutcome>> {
    if run.phase == RunPhase::Succeeded && let Some(answer) = &turn.final_answer {
        ensure!(turn.pending_model.is_none() && turn.pending_tool.is_none() && turn.queued_tools.is_empty(),
            "original succeeded run still has pending native effects");
        ensure!(!turn.cancelled && turn.model_calls > 0 && turn.model_usage.len() == turn.model_calls
            && turn.completed_call_ids.len() == turn.tool_calls,
            "original succeeded checkpoint has inconsistent completion counts");
        owner.confirm_durable().await?;
        return Ok(Some(RunOutcome::Completed(answer.clone())));
    }
    if turn.pending_model.is_none() && turn.pending_tool.is_none() {
        if run.phase == RunPhase::Cancelled {
            owner.confirm_durable().await?;
            return Ok(Some(RunOutcome::Cancelled));
        }
        ensure!(run.phase != RunPhase::Failed, "original run is closed as Failed; no fresh execution is permitted");
    }
    Ok(None)
}

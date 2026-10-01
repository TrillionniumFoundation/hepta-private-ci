//! Propagate the existing Agentd run owner's stop intent to physical observation.
//! This observes control state; it cannot dispatch or grant effect authority.

use codex_hepta_agentd::AgentRunPhase;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativePreEffectAbortToken;
use tokio::time::Instant;
use tokio::time::timeout_at;

use super::LOCAL_CANCELLED;
use super::LOCAL_DEADLINE_ELAPSED;
use super::NativeBoundaryStatus;
use super::NativeIntelligenceRunBinding;
use super::NativeRunOutput;
use super::NativeRunStatus;
use super::RPC_TIMEOUT;
use super::classify_observation_failure;

#[derive(Clone)]
pub(super) struct NativeIntelligenceObservationBindingV1 {
    pub(super) run: NativeIntelligenceRunBinding,
    pub(super) revision: u64,
    pub(super) generation: u64,
}

#[derive(Clone, Copy)]
pub(super) enum NativeIntelligenceObservationPhaseV1 {
    Streaming,
    Terminal(AgentRunPhase),
    Reconciliation(AgentRunPhase),
}

impl NativeIntelligenceObservationBindingV1 {
    pub(super) async fn before_send(
        &mut self,
        owner: &AgentdClient,
        control: &mut DurableInferenceControl,
        proof: NativePreEffectAbortToken,
        deadline: Instant,
    ) -> super::Result<NativePreEffectAbortToken> {
        match self
            .require_unstopped(
                owner,
                deadline,
                NativeIntelligenceObservationPhaseV1::Streaming,
            )
            .await
        {
            Ok(()) => Ok(proof),
            Err(reason) => {
                // This live, one-shot proof still establishes that no model
                // effect was sent. Recovery cannot synthesize this release.
                control.abort_native_before_effect(proof, reason.clone())?;
                Err(reason.into())
            }
        }
    }

    pub(super) async fn revalidate_terminal(
        &mut self,
        owner: &AgentdClient,
        output: &mut NativeRunOutput,
        deadline: Instant,
    ) {
        let phase = NativeIntelligenceObservationPhaseV1::Terminal(physical_phase(output.status));
        self.revalidate_observation(owner, output, deadline, phase)
            .await;
    }

    pub(super) async fn revalidate_recovered_terminal(
        &mut self,
        owner: &AgentdClient,
        output: &mut NativeRunOutput,
        deadline: Instant,
    ) {
        let phase =
            NativeIntelligenceObservationPhaseV1::Reconciliation(physical_phase(output.status));
        self.revalidate_observation(owner, output, deadline, phase)
            .await;
    }

    async fn revalidate_observation(
        &mut self,
        owner: &AgentdClient,
        output: &mut NativeRunOutput,
        deadline: Instant,
        phase: NativeIntelligenceObservationPhaseV1,
    ) {
        if let Err(reason) = self.require_unstopped(owner, deadline, phase).await {
            if matches!(
                output.boundary_status,
                NativeBoundaryStatus::Indeterminate
                    | NativeBoundaryStatus::Succeeded
                    | NativeBoundaryStatus::Failed
                    | NativeBoundaryStatus::Interrupted
            ) {
                output.boundary_status = classify_observation_failure(&reason);
            }
            output.stop_reason = Some(match output.stop_reason.take() {
                Some(existing) => format!("{existing}; {reason}").chars().take(1024).collect(),
                None => reason,
            });
        }
    }

    pub(super) async fn require_unstopped(
        &mut self,
        owner: &AgentdClient,
        deadline: Instant,
        phase: NativeIntelligenceObservationPhaseV1,
    ) -> std::result::Result<(), String> {
        let checked = timeout_at(
            deadline.min(Instant::now() + RPC_TIMEOUT),
            owner.run_status(self.run.run_id.clone()),
        )
        .await;
        let run = match checked {
            Ok(Ok(Some(run))) => run,
            Ok(Ok(None)) => {
                return Err("intelligence run disappeared during observation".to_string());
            }
            Ok(Err(_)) => {
                return Err("intelligence run status unavailable during observation".to_string());
            }
            Err(_) if Instant::now() >= deadline => return Err(LOCAL_DEADLINE_ELAPSED.to_string()),
            Err(_) => return Err("intelligence run status check timed out".to_string()),
        };
        if run.run_id != self.run.run_id
            || run.generation != self.generation
            || run.context_digest.as_deref() != Some(self.run.context_digest.as_str())
            || run.compilation_receipt_digest.as_deref() != Some(self.run.envelope_digest.as_str())
            || run.revision < self.revision
        {
            return Err("intelligence run identity changed during observation".to_string());
        }
        match run.phase {
            AgentRunPhase::ContextAttached
                if matches!(
                    phase,
                    NativeIntelligenceObservationPhaseV1::Reconciliation(_)
                ) && run.revision == self.run.expected_revision
                    && !run.terminal_observed
                    && run.cancel_reason.is_none() =>
            {
                // This permits projection of an already-observed physical
                // terminal into rehydrated state, never another model send.
                Ok(())
            }
            AgentRunPhase::Dispatched
                if !run.terminal_observed
                    && run.cancel_reason.is_none()
                    && (if matches!(
                        phase,
                        NativeIntelligenceObservationPhaseV1::Reconciliation(_)
                    ) {
                        self.run.expected_revision.checked_add(1) == Some(run.revision)
                    } else {
                        run.revision == self.revision
                    }) =>
            {
                self.revision = run.revision;
                Ok(())
            }
            AgentRunPhase::Indeterminate
                if matches!(
                    phase,
                    NativeIntelligenceObservationPhaseV1::Reconciliation(_)
                ) && self
                    .run
                    .expected_revision
                    .checked_add(1)
                    .is_some_and(|dispatch_revision| run.revision >= dispatch_revision)
                    && !run.terminal_observed
                    && run.cancel_reason.is_none() =>
            {
                // An authenticated Full terminal can resolve a lost-ack run.
                // Streaming never treats this historical state as send permission.
                self.revision = run.revision;
                Ok(())
            }
            AgentRunPhase::Cancelling | AgentRunPhase::Cancelled => {
                // The existing cancellation path can now publish a genuine
                // late terminal using the observed owner revision. It cannot
                // promote that fact back to successful execution authority.
                self.revision = run.revision;
                Err(LOCAL_CANCELLED.to_string())
            }
            AgentRunPhase::Succeeded | AgentRunPhase::Failed
                if matches!(phase, NativeIntelligenceObservationPhaseV1::Terminal(expected) | NativeIntelligenceObservationPhaseV1::Reconciliation(expected) if expected == run.phase)
                    && run.terminal_observed =>
            {
                self.revision = run.revision;
                if run.cancel_reason.is_some() {
                    Err(LOCAL_CANCELLED.to_string())
                } else {
                    Ok(())
                }
            }
            AgentRunPhase::Admitted
            | AgentRunPhase::ContextAttached
            | AgentRunPhase::Dispatched
            | AgentRunPhase::Succeeded
            | AgentRunPhase::Failed
            | AgentRunPhase::Indeterminate => {
                Err("intelligence run requires terminal reconciliation".to_string())
            }
        }
    }
}

fn physical_phase(status: NativeRunStatus) -> AgentRunPhase {
    match status {
        NativeRunStatus::Completed => AgentRunPhase::Succeeded,
        NativeRunStatus::Failed => AgentRunPhase::Failed,
        NativeRunStatus::Interrupted => AgentRunPhase::Cancelled,
        NativeRunStatus::Indeterminate => AgentRunPhase::Indeterminate,
    }
}

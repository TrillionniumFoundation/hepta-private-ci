//! Drive the original native turn and observe cancellation under Agentd.

use super::*;
use std::time::Duration;
use codex_hepta_native_agent::{ModelPort, ModelRequest, ObservedModelCompletion, ResponsesStream, ToolObservation, ToolPort};
use codex_hepta_types::RuntimeToolIntentV1;
use crate::native_ports::NativeProductionPorts;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum NativeDriveMode {
    Live,
    ObserveOriginal,
}

/// Observer projection of the same ports. It creates no authority or store and
/// never asks the original writer for a new grant while recovering old effects.
struct NativeDrivePorts {
    original: NativeProductionPorts,
    mode: NativeDriveMode,
}

impl ModelPort for NativeDrivePorts {
    async fn open(&self, request: &ModelRequest) -> Result<ResponsesStream> {
        ensure!(self.mode == NativeDriveMode::Live, "cold native recovery cannot open a new model POST");
        self.original.open(request).await
    }

    async fn reconcile(&self, request: &ModelRequest, response_id: &str) -> Result<Option<ObservedModelCompletion>> {
        self.original.reconcile(request, response_id).await
    }
}

impl ToolPort for NativeDrivePorts {
    async fn execute_or_observe(&self, intent: &RuntimeToolIntentV1, arguments: &[u8]) -> Result<ToolObservation> {
        match self.mode {
            NativeDriveMode::Live => self.original.execute_or_observe(intent, arguments).await,
            NativeDriveMode::ObserveOriginal => {
                intent.validate()?;
                ensure!(intent.arguments_digest == Digest32::of_bytes(arguments), "cold recovery changed original tool arguments");
                self.original.observe(intent).await
            }
        }
    }

    async fn observe(&self, intent: &RuntimeToolIntentV1) -> Result<ToolObservation> {
        self.original.observe(intent).await
    }

    async fn cancel(&self, intent: &RuntimeToolIntentV1) -> Result<()> {
        self.original.cancel(intent).await
    }
}

impl AgentdNativeHost {
    pub(super) async fn drive(&self, agent: &NativeAgent, owner: NativeThreadTurnOwner<NativeProductionAdmission>, admission: Arc<NativeProductionAdmission>, mut turn: TurnState, cancellation: &CancellationToken, mode: NativeDriveMode, entry_owner: NativeEntryOwner) -> Result<NativeTurnResult> {
        let state = self.gate.state()?;
        let execution_revision = if mode == NativeDriveMode::Live {
            Some(admission.fresh_revision.context("live native execution has no dispatched revision")?)
        } else { None };
        let observation_revision = admission.observation_revision;
        let ports = NativeDrivePorts { original: NativeProductionPorts { admission, model:self.model.clone(), runtime:self.runtime.clone(), entry_owner }, mode };
        let local_cancel = cancellation.child_token();
        let original = state.native_run_receipt(&owner.anchor().checkpoint.operation_id)?;
        let original_cancelled = mode == NativeDriveMode::ObserveOriginal
            && (original.phase == RunPhase::Cancelled
                || (matches!(original.phase, RunPhase::Indeterminate | RunPhase::Cancelling) && original.cancel_reason.is_some()));
        if original_cancelled { local_cancel.cancel(); }
        let mut monitor = tokio::time::interval(Duration::from_millis(50));
        let mut cancelled_at = None;
        let result = {
            let running = agent.run(&owner, &ports, &ports, &mut turn, &local_cancel);
            tokio::pin!(running);
            loop {
                tokio::select! {
                    result = &mut running => break result,
                    _ = monitor.tick() => {
                        let original_cancelled = mode == NativeDriveMode::Live
                            && state.native_observation_cancelled(&owner.anchor().checkpoint.operation_id).unwrap_or(true);
                        if original_cancelled || cancellation.is_cancelled() {
                            local_cancel.cancel();
                            let since = cancelled_at.get_or_insert_with(tokio::time::Instant::now);
                            if since.elapsed() >= Duration::from_secs(3) {
                                break Err(anyhow::anyhow!("native original owner stopped; pending operations require observation"));
                            }
                        }
                    }
                }
            }
        };
        if local_cancel.is_cancelled() && let Some(pending) = &turn.pending_tool {
            let _ = tokio::time::timeout(Duration::from_secs(2), ports.cancel(&pending.intent)).await;
        }
        let (mut outcome, phase) = match result {
            Ok(RunOutcome::Completed(_)) if original_cancelled => (RunOutcome::Cancelled, RunPhase::Cancelled),
            Ok(RunOutcome::Completed(answer)) => (RunOutcome::Completed(answer), RunPhase::Succeeded),
            Ok(RunOutcome::Cancelled) => (RunOutcome::Cancelled, RunPhase::Cancelled),
            Ok(outcome @ (RunOutcome::PendingModel | RunOutcome::PendingTool)) => (outcome, RunPhase::Indeterminate),
            Err(error) => {
                // The durable admission/checkpoint is the recovery source even
                // if current authority no longer permits a final checkpoint.
                if let Some(revision) = execution_revision {
                    state.observe_native_run_at_revision(&owner.anchor().checkpoint.operation_id, revision, RunPhase::Indeterminate)?;
                } else {
                    state.observe_native_recovery(&owner.anchor().checkpoint.operation_id, observation_revision, RunPhase::Indeterminate)?;
                }
                return Err(error);
            }
        };
        let run = if let Some(revision) = execution_revision {
            state.observe_native_run_at_revision(&owner.anchor().checkpoint.operation_id, revision, phase)?
        } else { state.observe_native_recovery(&owner.anchor().checkpoint.operation_id, observation_revision, phase)? };
        if mode == NativeDriveMode::ObserveOriginal {
            if run.phase == RunPhase::Cancelled && matches!(outcome, RunOutcome::Completed(_) | RunOutcome::Cancelled) {
                outcome = RunOutcome::Cancelled;
            }
            ensure!(run.phase != RunPhase::Failed || matches!(outcome, RunOutcome::PendingModel | RunOutcome::PendingTool),
                "original run is closed as Failed; observed results cannot replace its owner decision");
        }
        Ok(NativeTurnResult { outcome, state:turn, run })
    }
}

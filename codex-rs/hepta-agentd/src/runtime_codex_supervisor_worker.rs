use std::str::FromStr;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_infer_core::durable_control::native::{NativeRunOutput, NativeRunStatus};
use codex_hepta_types::{Digest32, StableId};
use tokio::time::{MissedTickBehavior, interval};
use tokio_util::sync::CancellationToken;

use super::super::super::persistence::{
    OperationPaths, dispatch_is_fenced, read_manifest, read_receipt_if_present,
    revalidate_external_files, validate_manifest_owner, validate_owner,
};
use super::super::super::{
    ProcessRuntimeCodexExecutorV1, RuntimeCodexExecutionReceiptV1, RuntimeCodexExecutorV1,
    RuntimeCodexOwnerV1,
};
use super::{DispatchState, Job};
use crate::{AgentRunPhase, AgentRunReceipt, AgentdClient, AgentdError, AgentdIdentity};

const STATUS_POLL_INTERVAL: Duration = Duration::from_millis(50);

pub(super) async fn run_job(
    executor: Arc<ProcessRuntimeCodexExecutorV1>,
    owner: RuntimeCodexOwnerV1,
    identity: AgentdIdentity,
    job: Job,
    lifetime: CancellationToken,
) -> Result<(), AgentdError> {
    let client = AgentdClient::new(
        identity.control_socket.clone(),
        identity.agent_id.clone(),
        identity.spawn_generation,
    )?;
    let run_id = job.input.run_id().to_string();
    if lifetime.is_cancelled() {
        job.cancellation.cancel();
    }
    let execution = executor.execute(owner.clone(), job.input, job.cancellation.clone());
    tokio::pin!(execution);
    let mut poll = interval(STATUS_POLL_INTERVAL);
    poll.set_missed_tick_behavior(MissedTickBehavior::Skip);
    let mut stopping = false;
    let outcome = loop {
        tokio::select! {
            result = &mut execution => break result,
            _ = lifetime.cancelled(), if !stopping => {
                stopping = true;
                job.cancellation.cancel();
            }
            _ = poll.tick() => {
                if let Ok(Some(status)) = client.run_status(run_id.clone()).await
                    && matches!(status.phase, AgentRunPhase::Cancelling | AgentRunPhase::Cancelled)
                {
                    job.cancellation.cancel();
                }
            }
        }
    };
    match outcome {
        Ok(receipt) => reconcile_receipt(&client, &receipt).await,
        Err(error) => {
            let stable_id = StableId::new(run_id.clone()).map_err(|invalid| {
                AgentdError::Protocol(format!("runtime.codex run id became invalid: {invalid}"))
            })?;
            let dispatch = dispatch_state(&executor, &owner, &stable_id)?;
            reconcile_error(&client, &run_id, dispatch).await?;
            eprintln!("runtime.codex run {run_id} reconciled after execution error: {error}");
            Ok(())
        }
    }
}

fn dispatch_state(
    executor: &ProcessRuntimeCodexExecutorV1,
    owner: &RuntimeCodexOwnerV1,
    run_id: &StableId,
) -> Result<DispatchState, AgentdError> {
    validate_owner(executor, owner)?;
    revalidate_external_files(executor)?;
    let key = Digest32::of_bytes(run_id.as_str().as_bytes()).to_string();
    let paths = OperationPaths::for_directory(&executor.journal_root.join(key));
    match std::fs::symlink_metadata(&paths.directory) {
        Ok(metadata) if metadata.is_dir() && !metadata.file_type().is_symlink() => {}
        Ok(_) => {
            return Err(AgentdError::Protocol(
                "runtime.codex operation path is not a canonical directory".to_string(),
            ));
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Ok(DispatchState::Absent);
        }
        Err(error) => return Err(error.into()),
    }
    let manifest = read_manifest(&paths.manifest)?;
    validate_manifest_owner(&manifest, owner, executor.worker_artifact_digest)?;
    if manifest.run_id != run_id.as_str() {
        return Err(AgentdError::Protocol(
            "runtime.codex operation directory has the wrong run identity".to_string(),
        ));
    }
    if read_receipt_if_present(&paths.receipt, &manifest)?.is_some() {
        return Ok(DispatchState::Terminal);
    }
    if dispatch_is_fenced(&paths, &manifest)? {
        Ok(DispatchState::Fenced)
    } else {
        Ok(DispatchState::Prepared)
    }
}

async fn reconcile_receipt(
    client: &AgentdClient,
    receipt: &RuntimeCodexExecutionReceiptV1,
) -> Result<(), AgentdError> {
    let current = client
        .run_status(receipt.run_id.clone())
        .await?
        .ok_or_else(|| AgentdError::Protocol("runtime.codex run disappeared".to_string()))?;
    let (target, terminal_observed) = terminal_projection(&receipt.output);
    if current.terminal_observed {
        return if current.phase == target {
            Ok(())
        } else {
            Err(AgentdError::Protocol(
                "runtime.codex receipt conflicts with Agentd terminal state".to_string(),
            ))
        };
    }
    let current = ensure_dispatched(client, current).await?;
    client
        .run_observe_terminal(
            receipt.run_id.clone(),
            current.revision,
            target,
            terminal_observed,
        )
        .await?;
    Ok(())
}

fn terminal_projection(output: &NativeRunOutput) -> (AgentRunPhase, bool) {
    if output.succeeded() {
        return (AgentRunPhase::Succeeded, true);
    }
    match output.status {
        NativeRunStatus::Failed => (AgentRunPhase::Failed, true),
        NativeRunStatus::Interrupted => (AgentRunPhase::Cancelled, true),
        NativeRunStatus::Completed | NativeRunStatus::Indeterminate => {
            (AgentRunPhase::Indeterminate, false)
        }
    }
}

async fn reconcile_error(
    client: &AgentdClient,
    run_id: &str,
    dispatch: DispatchState,
) -> Result<(), AgentdError> {
    let current = client
        .run_status(run_id.to_string())
        .await?
        .ok_or_else(|| AgentdError::Protocol("runtime.codex run disappeared".to_string()))?;
    if current.terminal_observed {
        return Ok(());
    }
    match dispatch {
        DispatchState::Absent | DispatchState::Prepared => {
            client
                .run_cancel(
                    run_id.to_string(),
                    current.revision,
                    "runtime_codex_not_dispatched".to_string(),
                )
                .await?;
        }
        DispatchState::Fenced | DispatchState::Terminal => {
            let current = ensure_dispatched(client, current).await?;
            client
                .run_observe_terminal(
                    run_id.to_string(),
                    current.revision,
                    AgentRunPhase::Indeterminate,
                    false,
                )
                .await?;
        }
    }
    Ok(())
}

async fn ensure_dispatched(
    client: &AgentdClient,
    current: AgentRunReceipt,
) -> Result<AgentRunReceipt, AgentdError> {
    match current.phase {
        AgentRunPhase::ContextAttached => {
            client
                .run_mark_dispatched(current.run_id.clone(), current.revision)
                .await
        }
        AgentRunPhase::Dispatched
        | AgentRunPhase::Cancelling
        | AgentRunPhase::Indeterminate
        | AgentRunPhase::Cancelled
        | AgentRunPhase::Succeeded
        | AgentRunPhase::Failed => Ok(current),
        AgentRunPhase::Admitted => Err(AgentdError::Protocol(
            "runtime.codex run lost its context attachment".to_string(),
        )),
    }
}

pub(super) async fn cancel_queued(identity: &AgentdIdentity, job: &Job) -> Result<(), AgentdError> {
    job.cancellation.cancel();
    let client = AgentdClient::new(
        identity.control_socket.clone(),
        identity.agent_id.clone(),
        identity.spawn_generation,
    )?;
    let run_id = job.input.run_id().to_string();
    let Some(current) = client.run_status(run_id.clone()).await? else {
        return Ok(());
    };
    if !current.terminal_observed
        && matches!(
            current.phase,
            AgentRunPhase::Admitted | AgentRunPhase::ContextAttached
        )
    {
        client
            .run_cancel(
                run_id,
                current.revision,
                "runtime_codex_owner_stopping".to_string(),
            )
            .await?;
    }
    Ok(())
}

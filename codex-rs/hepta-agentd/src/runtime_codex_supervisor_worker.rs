use std::sync::Arc;
use std::time::Duration;

use codex_hepta_infer_core::durable_control::native::{NativeRunOutput, NativeRunStatus};
use codex_hepta_types::{Digest32, StableId};
use tokio::time::{MissedTickBehavior, interval};
use tokio_util::sync::CancellationToken;

use super::super::super::archive::read_archived_receipt;
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
    let recovery_input = job.input.clone();
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
            // Archive publication precedes live-directory deletion. A lost
            // directory-sync acknowledgement may therefore leave exact
            // immutable terminal evidence even though the live path is gone.
            // Observe that evidence first and never relabel it as pre-dispatch.
            if let Some(receipt) = read_archived_receipt(
                &executor,
                &owner,
                &recovery_input,
                recovery_input.digest()?,
            )? {
                reconcile_receipt(&client, &receipt).await?;
                eprintln!(
                    "runtime.codex run {run_id} recovered an archived terminal receipt after execution error: {error}"
                );
                return Ok(());
            }

            let stable_id = StableId::new(run_id.clone()).map_err(|invalid| {
                AgentdError::Protocol(format!("runtime.codex run id became invalid: {invalid}"))
            })?;
            match dispatch_state(&executor, &owner, &stable_id)? {
                DispatchState::Terminal => {
                    // A failure after the immutable live receipt was published
                    // must replay that exact terminal evidence, not downgrade a
                    // known terminal result to Indeterminate.
                    let receipt = terminal_receipt(&executor, &owner, &stable_id)?;
                    reconcile_receipt(&client, &receipt).await?;
                    eprintln!(
                        "runtime.codex run {run_id} recovered an existing terminal receipt after execution error: {error}"
                    );
                }
                DispatchState::Fenced => {
                    // Close canonical admission immediately. Periodic/startup
                    // reconciliation later replaces this conservative latch
                    // with the exact durable unresolved counts.
                    ProcessRuntimeCodexExecutorV1::mark_agentd_supervisor_recovery_required()?;
                    reconcile_error(&client, &run_id, DispatchState::Fenced).await?;
                    eprintln!(
                        "runtime.codex run {run_id} entered reconcile-only recovery after execution error: {error}"
                    );
                }
                DispatchState::Absent => {
                    reconcile_error(&client, &run_id, DispatchState::Absent).await?;
                    eprintln!(
                        "runtime.codex run {run_id} cancelled before durable process admission after execution error: {error}"
                    );
                }
                DispatchState::Prepared => {
                    reconcile_error(&client, &run_id, DispatchState::Prepared).await?;
                    eprintln!(
                        "runtime.codex run {run_id} cancelled before dispatch fencing after execution error: {error}"
                    );
                }
            }
            Ok(())
        }
    }
}

fn operation_paths(
    executor: &ProcessRuntimeCodexExecutorV1,
    run_id: &StableId,
) -> OperationPaths {
    let key = Digest32::of_bytes(run_id.as_str().as_bytes()).to_string();
    OperationPaths::for_directory(&executor.journal_root.join(key))
}

fn dispatch_state(
    executor: &ProcessRuntimeCodexExecutorV1,
    owner: &RuntimeCodexOwnerV1,
    run_id: &StableId,
) -> Result<DispatchState, AgentdError> {
    validate_owner(executor, owner)?;
    revalidate_external_files(executor)?;
    let paths = operation_paths(executor, run_id);
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

fn terminal_receipt(
    executor: &ProcessRuntimeCodexExecutorV1,
    owner: &RuntimeCodexOwnerV1,
    run_id: &StableId,
) -> Result<RuntimeCodexExecutionReceiptV1, AgentdError> {
    validate_owner(executor, owner)?;
    revalidate_external_files(executor)?;
    let paths = operation_paths(executor, run_id);
    let manifest = read_manifest(&paths.manifest)?;
    validate_manifest_owner(&manifest, owner, executor.worker_artifact_digest)?;
    if manifest.run_id != run_id.as_str() {
        return Err(AgentdError::Protocol(
            "runtime.codex terminal receipt directory has the wrong run identity".to_string(),
        ));
    }
    read_receipt_if_present(&paths.receipt, &manifest)?.ok_or_else(|| {
        AgentdError::Protocol(
            "runtime.codex operation was classified terminal without a readable receipt"
                .to_string(),
        )
    })
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
        DispatchState::Fenced => {
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
        DispatchState::Terminal => {
            return Err(AgentdError::Protocol(
                "terminal runtime.codex evidence must be reconciled from its immutable receipt"
                    .to_string(),
            ));
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

use std::process::ExitStatus;
use std::process::Stdio;
use std::time::Duration;

use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_types::Digest32;
use tokio::io::AsyncRead;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::process::Child;
use tokio::process::Command;
use tokio::time::Instant;
use tokio::time::sleep_until;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::MAX_PROCESS_ERROR_BYTES;
use super::MAX_PROCESS_OUTPUT_BYTES;
use super::ProcessRuntimeCodexExecutorV1;
use super::RuntimeCodexExecutionInputV1;
use super::RuntimeCodexExecutionReceiptV1;
use super::RuntimeCodexOwnerV1;
use super::persistence::OperationPaths;
use super::persistence::RuntimeCodexJobManifestV1;
use super::persistence::deadline_instant;
use super::persistence::validate_manifest_owner;
use crate::AgentdError;

pub(super) async fn spawn_worker(
    executor: &ProcessRuntimeCodexExecutorV1,
    owner: &RuntimeCodexOwnerV1,
    manifest: &RuntimeCodexJobManifestV1,
    paths: &OperationPaths,
    fresh_input: Option<&RuntimeCodexExecutionInputV1>,
    cancellation: CancellationToken,
) -> Result<RuntimeCodexExecutionReceiptV1, AgentdError> {
    validate_manifest_owner(manifest, owner, executor.worker_artifact_digest)?;
    let reconciled = fresh_input.is_none();
    let mut command = Command::new(&executor.worker_executable);
    command
        .current_dir(owner.home_root())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        .arg("--profile")
        .arg("native-app-server")
        .arg("--agentd-socket")
        .arg(owner.agentd_socket())
        .arg("--agent-id")
        .arg(owner.agent_id().as_str())
        .arg("--generation")
        .arg(owner.generation().to_string())
        .arg("--model")
        .arg(&manifest.model)
        .arg("--journal")
        .arg(&paths.native_journal)
        .arg("--request-id")
        .arg(&manifest.run_id)
        .arg("--maximum-in-flight")
        .arg(executor.maximum_in_flight.to_string())
        .arg("--final-use-authority-config")
        .arg(&executor.final_use_authority_config)
        .arg("--timeout-ms")
        .arg(manifest.timeout_ms.to_string());
    if let Some(input) = fresh_input {
        if input.digest()?.to_string() != manifest.input_digest {
            return Err(AgentdError::Protocol(
                "runtime.codex fresh input no longer matches its durable manifest".to_string(),
            ));
        }
        command
            .arg("--intelligence-run-id")
            .arg(input.run_id().as_str())
            .arg("--intelligence-revision")
            .arg(input.expected_revision().to_string())
            .arg("--intelligence-context-digest")
            .arg(input.context_digest().to_string())
            .arg("--intelligence-envelope-digest")
            .arg(input.envelope_digest().to_string());
        if let Some(query) = input.context_query() {
            command.arg("--context-query").arg(query);
        }
    } else {
        command.arg("--resume");
    }

    let mut child = command.spawn()?;
    let mut stdin = child.stdin.take().ok_or_else(|| {
        AgentdError::Protocol("runtime.codex worker stdin was not piped".to_string())
    })?;
    let stdout = child.stdout.take().ok_or_else(|| {
        AgentdError::Protocol("runtime.codex worker stdout was not piped".to_string())
    })?;
    let stderr = child.stderr.take().ok_or_else(|| {
        AgentdError::Protocol("runtime.codex worker stderr was not piped".to_string())
    })?;
    let prompt = fresh_input.map(|input| input.prompt().as_bytes().to_vec());
    let stdin_task = tokio::spawn(async move {
        if let Some(prompt) = prompt
            && let Err(error) = stdin.write_all(&prompt).await
            && error.kind() != std::io::ErrorKind::BrokenPipe
        {
            return Err(error);
        }
        match stdin.shutdown().await {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::BrokenPipe => Ok(()),
            Err(error) => Err(error),
        }
    });
    let stdout_task = tokio::spawn(read_bounded(stdout, MAX_PROCESS_OUTPUT_BYTES));
    let stderr_task = tokio::spawn(read_bounded(stderr, MAX_PROCESS_ERROR_BYTES));

    let deadline = deadline_instant(manifest.deadline_ms, reconciled)?;
    let (status, stop) = wait_for_worker(
        &mut child,
        &cancellation,
        deadline,
        executor.interrupt_grace,
    )
    .await?;
    stdin_task.await.map_err(|error| {
        AgentdError::Protocol(format!("runtime.codex stdin task failed: {error}"))
    })??;
    let stdout = stdout_task.await.map_err(|error| {
        AgentdError::Protocol(format!("runtime.codex stdout task failed: {error}"))
    })??;
    let stderr = stderr_task.await.map_err(|error| {
        AgentdError::Protocol(format!("runtime.codex stderr task failed: {error}"))
    })??;

    let output = parse_worker_output(&stdout).map_err(|parse_error| {
        let stderr = String::from_utf8_lossy(&stderr);
        AgentdError::Protocol(format!(
            "runtime.codex worker {stop} with status {status}; no valid bounded receipt: {parse_error}; stderr={}",
            bounded_text(&stderr, 1_024)
        ))
    })?;
    validate_worker_output(&output, manifest)?;
    let output_digest = Digest32::of_bytes(&serde_json::to_vec(&output)?);
    Ok(RuntimeCodexExecutionReceiptV1 {
        schema_version: super::JOB_SCHEMA_VERSION,
        run_id: manifest.run_id.clone(),
        input_digest: manifest.input_digest.clone(),
        worker_artifact_digest: manifest.worker_artifact_digest.clone(),
        reconciled,
        idempotent: false,
        process_exit_code: status.code(),
        output_digest: output_digest.to_string(),
        output,
    })
}

fn validate_worker_output(
    output: &NativeRunOutput,
    manifest: &RuntimeCodexJobManifestV1,
) -> Result<(), AgentdError> {
    if output.thread_id.is_empty()
        || output.turn_id.is_empty()
        || output.model != manifest.model
        || !output.terminal_observed
        || output
            .codex_terminal_correlation_digest
            .as_deref()
            .is_none_or(|digest| digest.parse::<Digest32>().is_err())
    {
        return Err(AgentdError::Protocol(
            "runtime.codex worker receipt is not an exact terminal observation".to_string(),
        ));
    }
    Ok(())
}

async fn wait_for_worker(
    child: &mut Child,
    cancellation: &CancellationToken,
    deadline: Instant,
    interrupt_grace: Duration,
) -> Result<(ExitStatus, &'static str), AgentdError> {
    tokio::select! {
        status = child.wait() => Ok((status?, "exited")),
        () = cancellation.cancelled() => {
            interrupt_and_wait(child, interrupt_grace).await.map(|status| (status, "cancelled"))
        }
        () = sleep_until(deadline) => {
            interrupt_and_wait(child, interrupt_grace).await.map(|status| (status, "deadline elapsed"))
        }
    }
}

async fn interrupt_and_wait(
    child: &mut Child,
    grace: Duration,
) -> Result<ExitStatus, AgentdError> {
    signal_interrupt(child)?;
    match timeout(grace, child.wait()).await {
        Ok(status) => Ok(status?),
        Err(_) => {
            child.start_kill()?;
            Ok(child.wait().await?)
        }
    }
}

#[cfg(unix)]
fn signal_interrupt(child: &mut Child) -> Result<(), AgentdError> {
    let pid = child
        .id()
        .ok_or_else(|| AgentdError::Protocol("runtime.codex child has no pid".to_string()))?;
    let pid = i32::try_from(pid)
        .map_err(|_| AgentdError::Protocol("runtime.codex child pid overflow".to_string()))?;
    // SAFETY: `pid` is the live child returned by Tokio and SIGINT carries no
    // pointer arguments. The return value is checked immediately.
    let result = unsafe { libc::kill(pid, libc::SIGINT) };
    if result == 0 {
        return Ok(());
    }
    let error = std::io::Error::last_os_error();
    if error.raw_os_error() == Some(libc::ESRCH) {
        Ok(())
    } else {
        Err(error.into())
    }
}

#[cfg(not(unix))]
fn signal_interrupt(child: &mut Child) -> Result<(), AgentdError> {
    child.start_kill().map_err(Into::into)
}

async fn read_bounded<R>(mut reader: R, maximum: usize) -> Result<Vec<u8>, AgentdError>
where
    R: AsyncRead + Unpin,
{
    let limit = u64::try_from(maximum)
        .map_err(|_| AgentdError::Protocol("process output bound overflow".to_string()))?
        .saturating_add(1);
    let mut bytes = Vec::new();
    reader.take(limit).read_to_end(&mut bytes).await?;
    if bytes.len() > maximum {
        return Err(AgentdError::Protocol(
            "runtime.codex process output exceeded its bound".to_string(),
        ));
    }
    Ok(bytes)
}

fn parse_worker_output(bytes: &[u8]) -> Result<NativeRunOutput, AgentdError> {
    let last = bytes
        .split(|byte| *byte == b'\n')
        .rev()
        .find(|line| !line.iter().all(|byte| byte.is_ascii_whitespace()))
        .ok_or_else(|| AgentdError::Protocol("runtime.codex worker emitted no receipt".to_string()))?;
    Ok(serde_json::from_slice(last)?)
}

fn bounded_text(value: &str, maximum_chars: usize) -> String {
    value.chars().take(maximum_chars).collect()
}

use std::panic::AssertUnwindSafe;
use std::sync::Arc;
use std::time::Duration;

use base64::Engine;
use base64::engine::general_purpose::STANDARD;
use codex_app_server_protocol::JSONRPCErrorError;
use codex_app_server_protocol::ProcessExitedNotification;
use codex_app_server_protocol::ProcessIndeterminateNotification;
use codex_app_server_protocol::ProcessIndeterminateReason;
use codex_app_server_protocol::ProcessOutputDeltaNotification;
use codex_app_server_protocol::ProcessOutputStream;
use codex_app_server_protocol::ServerNotification;
use codex_core::exec::ExecExpiration;
use codex_core::exec::ExecExpirationOutcome;
use codex_core::exec::IO_DRAIN_TIMEOUT_MS;
use codex_protocol::exec_output::bytes_to_string_smart;
use codex_utils_pty::ProcessHandle;
use codex_utils_pty::TerminalSize;
use futures::FutureExt;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio::sync::watch;

use super::manager::ProcessControl;
use super::manager::ProcessControlRequest;
use super::registry::ProcessRegistrationGuard;
use crate::error_code::invalid_request;
use crate::outgoing_message::ConnectionId;
use crate::outgoing_message::ConnectionRequestId;
use crate::outgoing_message::OutgoingMessageSender;

const EXEC_TIMEOUT_EXIT_CODE: i32 = 124;
const OUTPUT_CHUNK_SIZE_HINT: usize = 64 * 1024;

pub(super) struct RunProcessParams {
    pub(super) outgoing: Arc<OutgoingMessageSender>,
    pub(super) request_id: ConnectionRequestId,
    pub(super) process_handle: String,
    pub(super) session: Arc<ProcessHandle>,
    pub(super) stdout_rx: mpsc::Receiver<Vec<u8>>,
    pub(super) stderr_rx: mpsc::Receiver<Vec<u8>>,
    pub(super) exit_rx: oneshot::Receiver<i32>,
    pub(super) guard: ProcessRegistrationGuard,
    pub(super) control_rx: mpsc::Receiver<ProcessControlRequest>,
    pub(super) stream_stdin: bool,
    pub(super) stream_stdout_stderr: bool,
    pub(super) expiration: ExecExpiration,
    pub(super) output_bytes_cap: Option<usize>,
}

struct SpawnProcessOutputParams {
    connection_id: ConnectionId,
    process_handle: String,
    output_rx: mpsc::Receiver<Vec<u8>>,
    stdio_timeout_rx: watch::Receiver<bool>,
    outgoing: Arc<OutgoingMessageSender>,
    stream: ProcessOutputStream,
    stream_output: bool,
    output_bytes_cap: Option<usize>,
}

#[derive(Default)]
struct ProcessOutputCapture {
    text: String,
    cap_reached: bool,
}

pub(super) async fn run_process(params: RunProcessParams) {
    let RunProcessParams {
        outgoing,
        request_id,
        process_handle,
        session,
        stdout_rx,
        stderr_rx,
        exit_rx,
        mut guard,
        control_rx,
        stream_stdin,
        stream_stdout_stderr,
        expiration,
        output_bytes_cap,
    } = params;
    let mut control_rx = control_rx;
    let mut control_open = true;
    let expiration = expiration.wait_with_outcome();
    tokio::pin!(expiration);
    tokio::pin!(exit_rx);
    let mut expiration_outcome = None;
    let (stdio_timeout_tx, stdio_timeout_rx) = watch::channel(false);

    let stdout_handle = collect_spawn_process_output(SpawnProcessOutputParams {
        connection_id: request_id.connection_id,
        process_handle: process_handle.clone(),
        output_rx: stdout_rx,
        stdio_timeout_rx: stdio_timeout_rx.clone(),
        outgoing: Arc::clone(&outgoing),
        stream: ProcessOutputStream::Stdout,
        stream_output: stream_stdout_stderr,
        output_bytes_cap,
    });
    let stderr_handle = collect_spawn_process_output(SpawnProcessOutputParams {
        connection_id: request_id.connection_id,
        process_handle: process_handle.clone(),
        output_rx: stderr_rx,
        stdio_timeout_rx,
        outgoing: Arc::clone(&outgoing),
        stream: ProcessOutputStream::Stderr,
        stream_output: stream_stdout_stderr,
        output_bytes_cap,
    });

    let exit_observation = AssertUnwindSafe(async {
      loop {
        tokio::select! {
            control = control_rx.recv(), if control_open => {
                match control {
                    Some(ProcessControlRequest { control, response_tx }) => {
                        let result = match control {
                            ProcessControl::Write { delta, close_stdin } => {
                                handle_process_write(
                                    &session,
                                    stream_stdin,
                                    delta,
                                    close_stdin,
                                ).await
                            }
                            ProcessControl::Resize { size } => {
                                handle_process_resize(&session, size)
                            }
                            ProcessControl::Kill => {
                                session.request_terminate();
                                Ok(())
                            }
                        };
                        if let Some(response_tx) = response_tx
                            && response_tx.send(result).is_err()
                        {
                            tracing::debug!(
                                process_handle = %process_handle,
                                "process control response receiver dropped"
                            );
                        }
                    },
                    None => {
                        control_open = false;
                        session.request_terminate();
                    }
                }
            }
            outcome = &mut expiration, if expiration_outcome.is_none() => {
                expiration_outcome = Some(outcome);
                session.request_terminate();
            }
            exit = &mut exit_rx => {
                match exit {
                    Ok(code) => {
                        guard.observed_exit();
                        break Ok(if matches!(expiration_outcome, Some(ExecExpirationOutcome::TimedOut)) {
                            EXEC_TIMEOUT_EXIT_CODE
                        } else {
                            code
                        });
                    }
                    Err(_) => {
                        // Fence before output draining or any notification await.
                        guard.observation_lost();
                        break Err(ProcessIndeterminateReason::ExitObservationLost);
                    }
                }
            }
        }
      }
    }).catch_unwind().await;
    let exit_code = match exit_observation {
        Ok(observation) => observation,
        Err(_) => {
            guard.observation_lost();
            Err(ProcessIndeterminateReason::ExitObservationLost)
        }
    };

    // Preserve the original bounded drain for both observed and unknown outcomes.
    let timeout_handle = tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(IO_DRAIN_TIMEOUT_MS)).await;
        let _ = stdio_timeout_tx.send(true);
    });

    let stdout = stdout_handle.await.unwrap_or_default();
    let stderr = stderr_handle.await.unwrap_or_default();
    timeout_handle.abort();

    let notification = match exit_code {
        Ok(exit_code) => ServerNotification::ProcessExited(ProcessExitedNotification {
            process_handle,
            exit_code,
            stdout: stdout.text,
            stdout_cap_reached: stdout.cap_reached,
            stderr: stderr.text,
            stderr_cap_reached: stderr.cap_reached,
        }),
        Err(reason) => ServerNotification::ProcessIndeterminate(ProcessIndeterminateNotification {
            process_handle,
            reason,
            stdout: stdout.text,
            stdout_cap_reached: stdout.cap_reached,
            stderr: stderr.text,
            stderr_cap_reached: stderr.cap_reached,
        }),
    };
    outgoing
        .send_server_notification_to_connection_and_wait(request_id.connection_id, notification)
        .await;
}

fn collect_spawn_process_output(
    params: SpawnProcessOutputParams,
) -> tokio::task::JoinHandle<ProcessOutputCapture> {
    let SpawnProcessOutputParams {
        connection_id,
        process_handle,
        mut output_rx,
        mut stdio_timeout_rx,
        outgoing,
        stream,
        stream_output,
        output_bytes_cap,
    } = params;
    tokio::spawn(async move {
        let mut buffer: Vec<u8> = Vec::new();
        let mut observed_num_bytes = 0usize;
        let mut cap_reached = false;
        loop {
            let mut chunk = tokio::select! {
                chunk = output_rx.recv() => match chunk {
                    Some(chunk) => chunk,
                    None => break,
                },
                _ = stdio_timeout_rx.wait_for(|&v| v) => break,
            };
            while chunk.len() < OUTPUT_CHUNK_SIZE_HINT
                && let Ok(next_chunk) = output_rx.try_recv()
            {
                chunk.extend_from_slice(&next_chunk);
            }
            let capped_chunk = match output_bytes_cap {
                Some(output_bytes_cap) => {
                    let capped_chunk_len = output_bytes_cap
                        .saturating_sub(observed_num_bytes)
                        .min(chunk.len());
                    observed_num_bytes += capped_chunk_len;
                    &chunk[0..capped_chunk_len]
                }
                None => chunk.as_slice(),
            };
            cap_reached = Some(observed_num_bytes) == output_bytes_cap;
            if stream_output {
                tokio::select! {
                    _ = outgoing.send_server_notification_to_connection_and_wait(
                        connection_id,
                        ServerNotification::ProcessOutputDelta(ProcessOutputDeltaNotification {
                            process_handle: process_handle.clone(),
                            stream,
                            delta_base64: STANDARD.encode(capped_chunk),
                            cap_reached,
                        }),
                    ) => {}
                    _ = stdio_timeout_rx.wait_for(|&v| v) => break,
                }
            } else {
                buffer.extend_from_slice(capped_chunk);
            }
            if cap_reached {
                break;
            }
        }
        ProcessOutputCapture {
            text: bytes_to_string_smart(&buffer),
            cap_reached,
        }
    })
}

async fn handle_process_write(
    session: &ProcessHandle,
    stream_stdin: bool,
    delta: Vec<u8>,
    close_stdin: bool,
) -> Result<(), JSONRPCErrorError> {
    if !stream_stdin {
        return Err(invalid_request(
            "stdin streaming is not enabled for this process",
        ));
    }
    if !delta.is_empty() {
        session
            .writer_sender()
            .send(delta)
            .await
            .map_err(|_| invalid_request("stdin is already closed"))?;
    }
    if close_stdin {
        // Closing drops our sender; the writer task still drains any bytes
        // accepted above before its receiver observes EOF and closes stdin.
        session.close_stdin();
    }
    Ok(())
}

fn handle_process_resize(
    session: &ProcessHandle,
    size: TerminalSize,
) -> Result<(), JSONRPCErrorError> {
    session
        .resize(size)
        .map_err(|err| invalid_request(format!("failed to resize PTY: {err}")))
}

#[cfg(test)]
#[path = "process_exec_runtime_tests.rs"]
mod process_exec_runtime_tests;

#[cfg(test)]
#[path = "process_exec_drain_tests.rs"]
mod drain_tests;

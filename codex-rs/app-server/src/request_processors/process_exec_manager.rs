use std::collections::HashMap;
use std::collections::hash_map::Entry;
use std::sync::Arc;

use base64::Engine;
use base64::engine::general_purpose::STANDARD;
use codex_app_server_protocol::JSONRPCErrorError;
use codex_app_server_protocol::ProcessKillParams;
use codex_app_server_protocol::ProcessKillResponse;
use codex_app_server_protocol::ProcessResizePtyParams;
use codex_app_server_protocol::ProcessResizePtyResponse;
use codex_app_server_protocol::ProcessSpawnResponse;
use codex_app_server_protocol::ProcessWriteStdinParams;
use codex_app_server_protocol::ProcessWriteStdinResponse;
use codex_core::exec::ExecExpiration;
use codex_utils_absolute_path::AbsolutePathBuf;
use codex_utils_pty::TerminalSize;
use tokio::sync::Mutex;
use tokio::sync::mpsc;
use tokio::sync::oneshot;

use super::runtime::RunProcessParams;
use super::runtime::run_process;
use super::terminal_size_from_protocol;
use crate::error_code::internal_error;
use crate::error_code::invalid_params;
use crate::error_code::invalid_request;
use crate::outgoing_message::ConnectionId;
use crate::outgoing_message::ConnectionRequestId;
use crate::outgoing_message::OutgoingMessageSender;

#[derive(Clone, Default)]
pub(super) struct ProcessExecManager {
    sessions: Arc<Mutex<HashMap<ConnectionProcessHandle, ProcessSession>>>,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
struct ConnectionProcessHandle {
    connection_id: ConnectionId,
    process_handle: String,
}

#[derive(Clone)]
struct ProcessSession {
    control_tx: mpsc::Sender<ProcessControlRequest>,
}

pub(super) enum ProcessControl {
    Write { delta: Vec<u8>, close_stdin: bool },
    Resize { size: TerminalSize },
    Kill,
}

pub(super) struct ProcessControlRequest {
    pub(super) control: ProcessControl,
    pub(super) response_tx: Option<oneshot::Sender<Result<(), JSONRPCErrorError>>>,
}

pub(super) struct StartProcessParams {
    pub(super) outgoing: Arc<OutgoingMessageSender>,
    pub(super) request_id: ConnectionRequestId,
    pub(super) process_handle: String,
    pub(super) command: Vec<String>,
    pub(super) cwd: AbsolutePathBuf,
    pub(super) env: HashMap<String, String>,
    pub(super) expiration: ExecExpiration,
    pub(super) tty: bool,
    pub(super) stream_stdin: bool,
    pub(super) stream_stdout_stderr: bool,
    pub(super) output_bytes_cap: Option<usize>,
    pub(super) size: Option<TerminalSize>,
}

impl ProcessExecManager {
    pub(super) async fn start(&self, params: StartProcessParams) -> Result<(), JSONRPCErrorError> {
        let StartProcessParams {
            outgoing,
            request_id,
            process_handle,
            command,
            cwd,
            env,
            expiration,
            tty,
            stream_stdin,
            stream_stdout_stderr,
            output_bytes_cap,
            size,
        } = params;

        let (program, args) = command
            .split_first()
            .ok_or_else(|| invalid_request("command must not be empty"))?;
        let stream_stdin = tty || stream_stdin;
        let stream_stdout_stderr = tty || stream_stdout_stderr;
        let arg0 = None;
        let (control_tx, control_rx) = mpsc::channel(32);
        let process_key = ConnectionProcessHandle {
            connection_id: request_id.connection_id,
            process_handle: process_handle.clone(),
        };

        {
            let mut sessions = self.sessions.lock().await;
            match sessions.entry(process_key.clone()) {
                Entry::Occupied(_) => {
                    return Err(invalid_request(format!(
                        "duplicate active process handle: {process_handle:?}",
                    )));
                }
                Entry::Vacant(entry) => {
                    entry.insert(ProcessSession { control_tx });
                }
            }
        }

        let spawned = if tty {
            codex_utils_pty::spawn_pty_process(
                program,
                args,
                cwd.as_path(),
                &env,
                &arg0,
                size.unwrap_or_default(),
                &[],
            )
            .await
        } else if stream_stdin {
            codex_utils_pty::spawn_pipe_process(program, args, cwd.as_path(), &env, &arg0, &[])
                .await
        } else {
            codex_utils_pty::spawn_pipe_process_no_stdin(
                program,
                args,
                cwd.as_path(),
                &env,
                &arg0,
                &[],
            )
            .await
        };
        let spawned = match spawned {
            Ok(spawned) => spawned,
            Err(err) => {
                self.sessions.lock().await.remove(&process_key);
                return Err(internal_error(format!("failed to spawn process: {err}")));
            }
        };

        outgoing
            .send_response(request_id.clone(), ProcessSpawnResponse {})
            .await;

        let sessions = Arc::clone(&self.sessions);
        tokio::spawn(async move {
            run_process(RunProcessParams {
                outgoing,
                request_id,
                process_handle,
                spawned,
                control_rx,
                stream_stdin,
                stream_stdout_stderr,
                expiration,
                output_bytes_cap,
            })
            .await;
            sessions.lock().await.remove(&process_key);
        });

        Ok(())
    }

    pub(super) async fn write_stdin(
        &self,
        request_id: ConnectionRequestId,
        params: ProcessWriteStdinParams,
    ) -> Result<ProcessWriteStdinResponse, JSONRPCErrorError> {
        if params.delta_base64.is_none() && !params.close_stdin {
            return Err(invalid_params(
                "process/writeStdin requires deltaBase64 or closeStdin",
            ));
        }

        let delta = match params.delta_base64 {
            Some(delta_base64) => STANDARD
                .decode(delta_base64)
                .map_err(|err| invalid_params(format!("invalid deltaBase64: {err}")))?,
            None => Vec::new(),
        };

        self.send_control(
            request_id.connection_id,
            params.process_handle,
            ProcessControl::Write {
                delta,
                close_stdin: params.close_stdin,
            },
        )
        .await?;

        Ok(ProcessWriteStdinResponse {})
    }

    pub(super) async fn kill(
        &self,
        request_id: ConnectionRequestId,
        params: ProcessKillParams,
    ) -> Result<ProcessKillResponse, JSONRPCErrorError> {
        self.send_control(
            request_id.connection_id,
            params.process_handle,
            ProcessControl::Kill,
        )
        .await?;
        Ok(ProcessKillResponse {})
    }

    pub(super) async fn resize_pty(
        &self,
        request_id: ConnectionRequestId,
        params: ProcessResizePtyParams,
    ) -> Result<ProcessResizePtyResponse, JSONRPCErrorError> {
        self.send_control(
            request_id.connection_id,
            params.process_handle,
            ProcessControl::Resize {
                size: terminal_size_from_protocol(params.size)?,
            },
        )
        .await?;
        Ok(ProcessResizePtyResponse {})
    }

    pub(super) async fn connection_closed(&self, connection_id: ConnectionId) {
        let controls = {
            let mut sessions = self.sessions.lock().await;
            let process_handles = sessions
                .keys()
                .filter(|process_handle| process_handle.connection_id == connection_id)
                .cloned()
                .collect::<Vec<_>>();
            let mut controls = Vec::with_capacity(process_handles.len());
            for process_handle in process_handles {
                if let Some(control) = sessions.remove(&process_handle) {
                    controls.push(control);
                }
            }
            controls
        };

        for control in controls {
            let _ = control
                .control_tx
                .send(ProcessControlRequest {
                    control: ProcessControl::Kill,
                    response_tx: None,
                })
                .await;
        }
    }

    async fn send_control(
        &self,
        connection_id: ConnectionId,
        process_handle: String,
        control: ProcessControl,
    ) -> Result<(), JSONRPCErrorError> {
        let process_key = ConnectionProcessHandle {
            connection_id,
            process_handle,
        };
        let session = self
            .sessions
            .lock()
            .await
            .get(&process_key)
            .cloned()
            .ok_or_else(|| no_active_process_error(&process_key.process_handle))?;
        let (response_tx, response_rx) = oneshot::channel();
        session
            .control_tx
            .send(ProcessControlRequest {
                control,
                response_tx: Some(response_tx),
            })
            .await
            .map_err(|_| process_no_longer_running_error(&process_key.process_handle))?;
        response_rx
            .await
            .map_err(|_| process_no_longer_running_error(&process_key.process_handle))?
    }
}

fn no_active_process_error(process_handle: &str) -> JSONRPCErrorError {
    invalid_request(format!(
        "no active process for process handle {process_handle:?}"
    ))
}

fn process_no_longer_running_error(process_handle: &str) -> JSONRPCErrorError {
    invalid_request(format!("process {process_handle:?} is no longer running"))
}

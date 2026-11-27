use std::collections::HashMap;
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
use tokio::sync::mpsc;
use tokio::sync::oneshot;

use super::registry::ConnectionProcessHandle;
use super::registry::ProcessRegistry;
use super::registry::observation_lost_error;
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
    registry: Arc<ProcessRegistry>,
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

        // Admission and the first-unknown fence share one registry lock.
        // This reservation precedes the native spawn; existing reservations may finish.
        let guard = self.registry.admit(process_key, control_tx)?;
        let registration = Arc::clone(guard.registration());

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
                // The untyped helper error can follow native spawn/setup.
                // Dropping the pending guard fences admission; it is not no-effect proof.
                drop(guard);
                return Err(internal_error(format!("failed to spawn process: {err}")));
            }
        };

        let codex_utils_pty::SpawnedProcess {
            session,
            stdout_rx,
            stderr_rx,
            exit_rx,
        } = spawned;
        // This is the sole initialization site for a newly admitted registration.
        // The registry keeps this exact owner even if the connection/worker disappears.
        let session = Arc::clone(registration.owner.get_or_init(|| Arc::new(session)));

        outgoing
            .send_response(request_id.clone(), ProcessSpawnResponse {})
            .await;

        tokio::spawn(async move {
            run_process(RunProcessParams {
                outgoing,
                request_id,
                process_handle,
                session,
                stdout_rx,
                stderr_rx,
                exit_rx,
                guard,
                control_rx,
                stream_stdin,
                stream_stdout_stderr,
                expiration,
                output_bytes_cap,
            })
            .await;
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
        let registrations = self.registry.connection_closed(connection_id);
        for registration in registrations {
            if registration
                .control_tx
                .send(ProcessControlRequest {
                    control: ProcessControl::Kill,
                    response_tx: None,
                })
                .await
                .is_err()
            {
                self.registry.observation_lost(&registration);
            }
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
        let registration = self.registry.active(&process_key)?;
        let (response_tx, response_rx) = oneshot::channel();
        if registration
            .control_tx
            .send(ProcessControlRequest {
                control,
                response_tx: Some(response_tx),
            })
            .await
            .is_err()
        {
            self.registry.observation_lost(&registration);
            return Err(observation_lost_error(&process_key.process_handle));
        }
        match response_rx.await {
            Ok(result) => result,
            Err(_) => {
                self.registry.observation_lost(&registration);
                Err(observation_lost_error(&process_key.process_handle))
            }
        }
    }
}

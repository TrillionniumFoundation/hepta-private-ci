use std::collections::HashMap;
use std::sync::Arc;

use codex_app_server_protocol::ClientResponsePayload;
use codex_app_server_protocol::JSONRPCErrorError;
use codex_app_server_protocol::ProcessKillParams;
use codex_app_server_protocol::ProcessResizePtyParams;
use codex_app_server_protocol::ProcessSpawnParams;
use codex_app_server_protocol::ProcessTerminalSize;
use codex_app_server_protocol::ProcessWriteStdinParams;
use codex_core::exec::ExecExpiration;
use codex_exec_server::EnvironmentManager;
use codex_protocol::shell_environment::is_non_inheritable_env_var;
use codex_utils_pty::DEFAULT_OUTPUT_BYTES_CAP;
use codex_utils_pty::TerminalSize;
use tokio_util::sync::CancellationToken;

use crate::error_code::internal_error;
use crate::error_code::invalid_params;
use crate::error_code::invalid_request;
use crate::outgoing_message::ConnectionId;
use crate::outgoing_message::ConnectionRequestId;
use crate::outgoing_message::OutgoingMessageSender;

#[path = "process_exec_manager.rs"]
mod manager;
#[path = "process_exec_runtime.rs"]
mod runtime;

use manager::ProcessExecManager;
use manager::StartProcessParams;

#[derive(Clone)]
pub(crate) struct ProcessExecRequestProcessor {
    outgoing: Arc<OutgoingMessageSender>,
    environment_manager: Arc<EnvironmentManager>,
    process_exec_manager: ProcessExecManager,
}

impl ProcessExecRequestProcessor {
    pub(crate) fn new(
        outgoing: Arc<OutgoingMessageSender>,
        environment_manager: Arc<EnvironmentManager>,
    ) -> Self {
        Self {
            outgoing,
            environment_manager,
            process_exec_manager: ProcessExecManager::default(),
        }
    }

    pub(crate) async fn process_spawn(
        &self,
        request_id: ConnectionRequestId,
        params: ProcessSpawnParams,
    ) -> Result<(), JSONRPCErrorError> {
        self.require_local_environment()?;
        let ProcessSpawnParams {
            command,
            process_handle,
            cwd,
            tty,
            stream_stdin,
            stream_stdout_stderr,
            output_bytes_cap,
            timeout_ms,
            env: env_overrides,
            size,
        } = params;
        let method_name = "process/spawn";
        tracing::debug!("{method_name} command: {command:?}");
        if command.is_empty() {
            return Err(invalid_request("command must not be empty"));
        }
        if process_handle.is_empty() {
            return Err(invalid_request("processHandle must not be empty"));
        }
        if size.is_some() && !tty {
            return Err(invalid_params("process/spawn size requires tty: true"));
        }
        let mut env = std::env::vars().collect::<HashMap<_, _>>();
        if let Some(env_overrides) = env_overrides {
            for (key, value) in env_overrides {
                match value {
                    Some(value) => {
                        env.insert(key, value);
                    }
                    None => {
                        env.remove(&key);
                    }
                }
            }
        }
        env.retain(|name, _| !is_non_inheritable_env_var(name));
        let expiration = match timeout_ms {
            Some(Some(timeout_ms)) => match u64::try_from(timeout_ms) {
                Ok(timeout_ms) => timeout_ms.into(),
                Err(_) => {
                    return Err(invalid_params(format!(
                        "{method_name} timeoutMs must be non-negative, got {timeout_ms}"
                    )));
                }
            },
            Some(None) => ExecExpiration::Cancellation(CancellationToken::new()),
            None => ExecExpiration::DefaultTimeout,
        };
        let output_bytes_cap = output_bytes_cap.unwrap_or(Some(DEFAULT_OUTPUT_BYTES_CAP));
        let size = size.map(terminal_size_from_protocol).transpose()?;

        self.process_exec_manager
            .start(StartProcessParams {
                outgoing: self.outgoing.clone(),
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
            })
            .await?;

        Ok(())
    }

    pub(crate) async fn process_write_stdin(
        &self,
        request_id: ConnectionRequestId,
        params: ProcessWriteStdinParams,
    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {
        self.process_exec_manager
            .write_stdin(request_id, params)
            .await
            .map(|response| Some(response.into()))
    }

    pub(crate) async fn process_resize_pty(
        &self,
        request_id: ConnectionRequestId,
        params: ProcessResizePtyParams,
    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {
        self.process_exec_manager
            .resize_pty(request_id, params)
            .await
            .map(|response| Some(response.into()))
    }

    pub(crate) async fn process_kill(
        &self,
        request_id: ConnectionRequestId,
        params: ProcessKillParams,
    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {
        self.process_exec_manager
            .kill(request_id, params)
            .await
            .map(|response| Some(response.into()))
    }

    pub(crate) async fn connection_closed(&self, connection_id: ConnectionId) {
        self.process_exec_manager
            .connection_closed(connection_id)
            .await;
    }

    fn require_local_environment(&self) -> Result<(), JSONRPCErrorError> {
        self.environment_manager
            .try_local_environment()
            .is_some()
            .then_some(())
            .ok_or_else(|| internal_error("local environment is not configured"))
    }
}

fn terminal_size_from_protocol(
    size: ProcessTerminalSize,
) -> Result<TerminalSize, JSONRPCErrorError> {
    if size.rows == 0 || size.cols == 0 {
        return Err(invalid_params(
            "process size rows and cols must be greater than 0",
        ));
    }
    Ok(TerminalSize {
        rows: size.rows,
        cols: size.cols,
    })
}

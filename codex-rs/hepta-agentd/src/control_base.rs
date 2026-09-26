use std::io::ErrorKind;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use codex_uds::UnixListener;
use codex_uds::UnixStream;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::sync::Semaphore;
use tokio::task::JoinSet;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use crate::AGENTD_CONTROL_OVERLOAD_FRAME;
use crate::AGENTD_CONTROL_SCHEMA_VERSION;
use crate::AgentdError;
use crate::AgentdPayload;
use crate::AgentdRequest;
use crate::AgentdResponse;
use crate::AgentdState;
use crate::MAX_CONTROL_FRAME_BYTES;
use crate::control_budget::FRAME_IO_TIMEOUT;
use crate::control_budget::operation_timeout;
use crate::error::io_context;

const CONNECTION_CAPACITY: usize = 32;
const OVERLOAD_WRITE_TIMEOUT: Duration = Duration::from_millis(50);

pub(crate) struct AgentdControlServer {
    listener: UnixListener,
    socket_path: PathBuf,
    state: Arc<AgentdState>,
    cancellation: CancellationToken,
    connections: Arc<Semaphore>,
}

impl AgentdControlServer {
    pub(crate) async fn bind(
        socket_path: PathBuf,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<Self, AgentdError> {
        prepare_socket(&socket_path).await?;
        let listener = UnixListener::bind(&socket_path)
            .await
            .map_err(|error| io_context("bind agentd control socket", &socket_path, error))?;
        set_owner_only(&socket_path).await?;
        Ok(Self {
            listener,
            socket_path,
            state,
            cancellation,
            connections: Arc::new(Semaphore::new(CONNECTION_CAPACITY)),
        })
    }

    pub(crate) async fn run(mut self) -> Result<(), AgentdError> {
        let mut connections = JoinSet::new();
        loop {
            let stream = tokio::select! {
                _ = self.cancellation.cancelled() => {
                    connections.shutdown().await;
                    return Ok(());
                },
                _ = connections.join_next(), if !connections.is_empty() => continue,
                accepted = self.listener.accept() => accepted?,
            };
            // Reject an untrusted operating-system user before it can consume
            // one of the bounded connection permits or any protocol bytes.
            if stream.ensure_current_user_peer().is_err() {
                continue;
            }
            let Ok(permit) = Arc::clone(&self.connections).try_acquire_owned() else {
                let mut stream = stream;
                let _ = timeout(OVERLOAD_WRITE_TIMEOUT, async {
                    stream.write_all(AGENTD_CONTROL_OVERLOAD_FRAME).await?;
                    stream.shutdown().await
                })
                .await;
                continue;
            };
            let state = Arc::clone(&self.state);
            connections.spawn(async move {
                let _permit = permit;
                let _ = serve_connection(stream, state).await;
            });
        }
    }
}

impl Drop for AgentdControlServer {
    fn drop(&mut self) {
        if let Err(error) = std::fs::remove_file(&self.socket_path)
            && error.kind() != ErrorKind::NotFound
        {
            eprintln!(
                "failed to remove agentd control socket {}: {error}",
                self.socket_path.display()
            );
        }
    }
}

async fn serve_connection(stream: UnixStream, state: Arc<AgentdState>) -> Result<(), AgentdError> {
    let owner = Arc::clone(&state);
    serve_connection_with(stream, state, move |request| async move {
        owner
            .response(request.request_id, request.spawn_generation, request.method)
            .await
    })
    .await
}

async fn serve_connection_with<F, R>(
    stream: UnixStream,
    state: Arc<AgentdState>,
    handler: F,
) -> Result<(), AgentdError>
where
    F: FnOnce(AgentdRequest) -> R,
    R: std::future::Future<Output = Result<AgentdResponse, AgentdError>>,
{
    // Keep this check here as well as in the accept loop. Tests and future
    // in-process callers can invoke this transport boundary directly, and no
    // such path may bypass the kernel-reported peer identity gate.
    stream.ensure_current_user_peer()?;
    let (reader, mut writer) = tokio::io::split(stream);
    let mut reader = BufReader::new(reader).take(MAX_CONTROL_FRAME_BYTES + 1);
    let mut frame = Vec::new();
    let count = timeout(FRAME_IO_TIMEOUT, reader.read_until(b'\n', &mut frame))
        .await
        .map_err(|_| AgentdError::Protocol("agentd request frame timed out".to_string()))??;
    if count == 0 || count as u64 > MAX_CONTROL_FRAME_BYTES || !frame.ends_with(b"\n") {
        return Err(AgentdError::Protocol(
            "agentd control request must be one bounded newline JSON frame".to_string(),
        ));
    }
    let request: AgentdRequest = serde_json::from_slice(&frame)?;
    let request_id = request.request_id;
    let response = if request.schema_version != AGENTD_CONTROL_SCHEMA_VERSION {
        error_response(
            &state,
            request_id,
            "unsupported_schema",
            "unsupported agentd control schema",
        )
    } else {
        match timeout(operation_timeout(&request.method), handler(request)).await {
            Ok(Ok(response)) => response,
            Ok(Err(error)) => error_response(
                &state,
                request_id,
                "request_rejected",
                &error.to_string(),
            ),
            Err(_) => error_response(
                &state,
                request_id,
                "operation_timed_out",
                "operation acknowledgement timed out; reconcile the original identity before retrying",
            ),
        }
    };
    let mut bytes = serde_json::to_vec(&response)?;
    bytes.push(b'\n');
    if bytes.len() as u64 > MAX_CONTROL_FRAME_BYTES {
        return Err(AgentdError::Protocol(
            "agentd control response exceeded frame bound".to_string(),
        ));
    }
    timeout(FRAME_IO_TIMEOUT, async {
        writer.write_all(&bytes).await?;
        writer.shutdown().await
    })
    .await
    .map_err(|_| AgentdError::Protocol("agentd response frame timed out".to_string()))??;
    Ok(())
}

fn error_response(
    state: &AgentdState,
    request_id: u64,
    code: &str,
    message: &str,
) -> AgentdResponse {
    // Never echo an untrusted request generation into the response identity.
    // Refresh the owner fence when possible; a failed refresh already fences
    // the state and falls back only to this process's immutable spawn epoch.
    let current_generation = state
        .current_generation()
        .unwrap_or(state.identity().spawn_generation);
    AgentdResponse {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id,
        agent_id: state.identity().agent_id.clone(),
        spawn_generation: state.identity().spawn_generation,
        current_generation,
        payload: AgentdPayload::Error {
            code: code.to_string(),
            message: bounded_message(message),
        },
    }
}

fn bounded_message(message: &str) -> String {
    message.chars().take(512).collect()
}

async fn prepare_socket(socket_path: &Path) -> Result<(), AgentdError> {
    let parent = socket_path.parent().ok_or_else(|| {
        AgentdError::Invalid("agentd control socket has no parent directory".to_string())
    })?;
    codex_uds::prepare_private_socket_directory(parent)
        .await
        .map_err(|error| io_context("prepare agentd control socket directory", parent, error))?;
    match UnixStream::connect(socket_path).await {
        Ok(_) => {
            return Err(AgentdError::Io(std::io::Error::new(
                ErrorKind::AddrInUse,
                format!(
                    "agentd control socket is already live at {}",
                    socket_path.display()
                ),
            )));
        }
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(()),
        Err(error) if error.kind() == ErrorKind::ConnectionRefused => {}
        Err(_error) if !socket_path.exists() => return Ok(()),
        Err(error) => {
            return Err(io_context(
                /* operation */ "probe existing agentd control socket",
                /* path */ socket_path,
                /* source */ error,
            ));
        }
    }
    if codex_uds::is_stale_socket_path(socket_path)
        .await
        .map_err(|error| io_context("inspect stale agentd control socket", socket_path, error))?
    {
        tokio::fs::remove_file(socket_path).await.map_err(|error| {
            io_context("remove stale agentd control socket", socket_path, error)
        })?;
        Ok(())
    } else {
        Err(AgentdError::Io(std::io::Error::new(
            ErrorKind::AlreadyExists,
            format!(
                "agentd control socket path is not a stale socket: {}",
                socket_path.display()
            ),
        )))
    }
}

#[cfg(unix)]
async fn set_owner_only(path: &Path) -> Result<(), AgentdError> {
    use std::os::unix::fs::PermissionsExt;

    tokio::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
        .await
        .map_err(|error| {
            io_context(
                "set owner-only agentd control socket permissions",
                path,
                error,
            )
        })?;
    Ok(())
}

#[cfg(not(unix))]
async fn set_owner_only(_path: &Path) -> Result<(), AgentdError> {
    Ok(())
}

#[cfg(test)]
#[path = "control_transport_tests.rs"]
mod tests;
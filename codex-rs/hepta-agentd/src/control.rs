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
use crate::error::io_context;

const CONNECTION_CAPACITY: usize = 32;
const IO_TIMEOUT: Duration = Duration::from_secs(2);
const OVERLOAD_WRITE_TIMEOUT: Duration = Duration::from_millis(50);

pub(crate) struct AgentdControlServer {
    listener: UnixListener,
    socket_path: PathBuf,
    #[cfg(windows)]
    socket_entry: Option<codex_utils_path::windows_private_fs::PrivateSocket>,
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
        #[cfg(windows)]
        let directory = prepare_socket(&socket_path).await?;
        #[cfg(not(windows))]
        prepare_socket(&socket_path).await?;
        let listener = UnixListener::bind(&socket_path)
            .await
            .map_err(|error| io_context("bind agentd control socket", &socket_path, error))?;
        set_owner_only(&socket_path).await?;
        #[cfg(windows)]
        let socket_entry = directory
            .open_socket(socket_name(&socket_path)?)
            .map_err(|error| io_context("retain bound agentd control socket", &socket_path, error))?
            .ok_or_else(|| AgentdError::Invalid("bound control socket disappeared".to_string()))?;
        Ok(Self {
            listener,
            socket_path,
            #[cfg(windows)]
            socket_entry: Some(socket_entry),
            state,
            cancellation,
            connections: Arc::new(Semaphore::new(CONNECTION_CAPACITY)),
        })
    }

    pub(crate) async fn run(mut self) -> Result<(), AgentdError> {
        loop {
            let stream = tokio::select! {
                _ = self.cancellation.cancelled() => return Ok(()),
                accepted = self.listener.accept() => accepted?,
            };
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
            tokio::spawn(async move {
                let _permit = permit;
                let _ = timeout(IO_TIMEOUT, serve_connection(stream, state)).await;
            });
        }
    }
}

impl Drop for AgentdControlServer {
    fn drop(&mut self) {
        #[cfg(windows)]
        let cleanup = match self.socket_entry.take() {
            Some(entry) => entry.remove(),
            None => Ok(()),
        };
        #[cfg(not(windows))]
        let cleanup = std::fs::remove_file(&self.socket_path);
        if let Err(error) = cleanup
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
    let (reader, mut writer) = tokio::io::split(stream);
    let mut reader = BufReader::new(reader).take(MAX_CONTROL_FRAME_BYTES + 1);
    let mut frame = Vec::new();
    let count = reader.read_until(b'\n', &mut frame).await?;
    if count == 0 || count as u64 > MAX_CONTROL_FRAME_BYTES || !frame.ends_with(b"\n") {
        return Err(AgentdError::Protocol(
            "agentd control request must be one bounded newline JSON frame".to_string(),
        ));
    }
    let request: AgentdRequest = serde_json::from_slice(&frame)?;
    let response = if request.schema_version != AGENTD_CONTROL_SCHEMA_VERSION {
        error_response(
            &state,
            request.request_id,
            request.spawn_generation,
            "unsupported_schema",
            "unsupported agentd control schema",
        )
    } else {
        match state
            .response(request.request_id, request.spawn_generation, request.method)
            .await
        {
            Ok(response) => response,
            Err(error) => error_response(
                &state,
                request.request_id,
                request.spawn_generation,
                "request_rejected",
                &error.to_string(),
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
    writer.write_all(&bytes).await?;
    writer.shutdown().await?;
    Ok(())
}

fn error_response(
    state: &AgentdState,
    request_id: u64,
    spawn_generation: u64,
    code: &str,
    message: &str,
) -> AgentdResponse {
    AgentdResponse {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id,
        agent_id: state.identity().agent_id.clone(),
        spawn_generation: state.identity().spawn_generation,
        current_generation: spawn_generation,
        payload: AgentdPayload::Error {
            code: code.to_string(),
            message: bounded_message(message),
        },
    }
}

fn bounded_message(message: &str) -> String {
    message.chars().take(512).collect()
}

#[cfg(windows)]
fn socket_name(socket_path: &Path) -> Result<&str, AgentdError> {
    socket_path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| {
            AgentdError::Invalid("agentd control socket must have a UTF-8 filename".to_string())
        })
}

#[cfg(windows)]
async fn prepare_socket(
    socket_path: &Path,
) -> Result<codex_utils_path::windows_private_fs::PrivateSocketDirectory, AgentdError> {
    use codex_utils_path::windows_private_fs::PrivateSocketDirectory;

    let name = socket_name(socket_path)?;
    let parent = socket_path.parent().ok_or_else(|| {
        AgentdError::Invalid("agentd control socket has no parent directory".to_string())
    })?;
    let directory = PrivateSocketDirectory::open_or_create(parent)
        .map_err(|error| io_context("retain private agentd socket directory", parent, error))?;
    let probe_error = match UnixStream::connect(socket_path).await {
        Ok(_) => {
            return Err(AgentdError::Io(std::io::Error::new(
                ErrorKind::AddrInUse,
                format!(
                    "agentd control socket is already live at {}",
                    socket_path.display()
                ),
            )));
        }
        Err(error) => error,
    };
    let entry = directory
        .open_socket(name)
        .map_err(|error| io_context("inspect agentd control socket", socket_path, error))?;
    let Some(entry) = entry else {
        return Ok(directory);
    };
    if probe_error.kind() != ErrorKind::ConnectionRefused {
        return Err(io_context(
            "probe existing agentd control socket",
            socket_path,
            probe_error,
        ));
    }
    // The initial probe preserves the live-endpoint refusal. Only this second
    // probe, with the typed entry retained against replacement, admits cleanup.
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
        Err(error) if error.kind() == ErrorKind::ConnectionRefused => {}
        Err(error) => {
            return Err(io_context(
                "probe retained agentd control socket",
                socket_path,
                error,
            ));
        }
    }
    entry
        .remove()
        .map_err(|error| io_context("remove retained stale agentd socket", socket_path, error))?;
    Ok(directory)
}

#[cfg(not(windows))]
async fn prepare_socket(socket_path: &Path) -> Result<(), AgentdError> {
    let parent = socket_path.parent().ok_or_else(|| {
        AgentdError::Invalid("agentd control socket has no parent directory".to_string())
    })?;
    codex_uds::prepare_private_socket_directory(parent)
        .await
        .map_err(|error| io_context("prepare agentd control socket directory", parent, error))?;
    let probe_error = match UnixStream::connect(socket_path).await {
        Ok(_) => {
            return Err(AgentdError::Io(std::io::Error::new(
                ErrorKind::AddrInUse,
                format!(
                    "agentd control socket is already live at {}",
                    socket_path.display()
                ),
            )));
        }
        Err(error) => error,
    };
    // Windows can report ConnectionRefused for an absent AF_UNIX path.
    // Inspect the actual directory entry before classifying a failed probe as
    // a stale endpoint. Other metadata failures must not masquerade as absence.
    match tokio::fs::symlink_metadata(socket_path).await {
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(()),
        Err(error) => {
            return Err(io_context(
                "inspect agentd control socket",
                socket_path,
                error,
            ));
        }
        Ok(_) => {}
    }
    if probe_error.kind() != ErrorKind::ConnectionRefused {
        return Err(io_context(
            "probe existing agentd control socket",
            socket_path,
            probe_error,
        ));
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
#[path = "control_tests.rs"]
mod tests;
